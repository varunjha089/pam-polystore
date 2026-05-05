"""
QueryInterface — entry point of the IMS.

Receives a query (currently a dict; will become a SQL-ish DSL on Day 2),
walks it through every IMS stage, and returns a unified result.

Today the pipeline is mostly pass-through with timing instrumentation.
Days 2-4 will add real parsing, optimization, and parallelism.
"""
import time
from typing import Any, Dict

from .task_analyzer import TaskAnalyzer
from .plan_optimizer import PlanOptimizer
from .metadata_manager import MetadataManager
from .subquery_distributor import SubqueryDistributor
from .accumulator import Accumulator


class QueryInterface:
    def __init__(self):
        self.metadata    = MetadataManager()
        self.analyzer    = TaskAnalyzer(self.metadata)
        self.optimizer   = PlanOptimizer(self.metadata)
        self.distributor = SubqueryDistributor()
        self.accumulator = Accumulator()

    def execute(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run a query through the IMS pipeline.

        query schema (Day 1, will expand on Day 2):
            {
                "parameter": "COCL",
                "time": "201901"  | {"from": "201901", "to": "201906"},
                "region": null    | {"lat": [10, 30], "lon": [70, 90]},  # degrees
                "aggregations": ["mean", "max"]   # optional
            }
        """
        t0 = time.perf_counter()
        trace = {"stages": []}

        # 1. Task analysis: figure out what kind of query this is
        task = self.analyzer.analyze(query)
        trace["stages"].append({"stage": "analyze", "task_type": task["type"]})

        # 2. Plan optimization: pick sequential vs parallel, file pruning
        plan = self.optimizer.plan(task)
        trace["stages"].append({"stage": "plan",
                                "strategy": plan["strategy"],
                                "n_subqueries": len(plan["subqueries"]),
                                "n_pruned": plan["n_pruned"]})

        # 3. Distribute subqueries to the right engine and execute
        results, sub_timings = self.distributor.distribute(plan)
        trace["stages"].append({"stage": "distribute", "timings_ms": sub_timings})

        # 4. Accumulate into a single result
        final = self.accumulator.merge(results, task, query)

        total_ms = (time.perf_counter() - t0) * 1000
        trace["total_ms"] = round(total_ms, 2)
        final["_trace"] = trace
        return final

    def explain(self, query):
        """Return IMS plan + cost estimate without executing. Like SQL EXPLAIN."""
        task = self.analyzer.analyze(query)
        plan = self.optimizer.plan(task)
        plan["explanation"] = (
            "Region: {:,} cells, {} tile(s). "
            "Per-subquery: {:.2f} ms. "
            "N={}: sequential={:.1f} ms, parallel={:.1f} ms. "
            "Strategy: {}.".format(
                plan.get("area_cells", 0),
                plan.get("n_tiles_per_subquery", 1),
                plan.get("cost_per_subquery_ms", 0),
                plan.get("n_subqueries", 1),
                plan.get("sequential_cost_ms", 0),
                plan.get("parallel_cost_ms", 0),
                plan.get("strategy", "sequential").upper()
            )
        )
        return plan

