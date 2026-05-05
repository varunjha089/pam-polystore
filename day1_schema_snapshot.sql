--
-- PostgreSQL database dump
--

\restrict QEIxvU36254NlDnpMseztPk5ARanX9dwhpyxy2SvykDLsUryMklVlfxtapG1lLr

-- Dumped from database version 14.22 (Ubuntu 14.22-0ubuntu0.22.04.1)
-- Dumped by pg_dump version 14.22 (Ubuntu 14.22-0ubuntu0.22.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: coord_axis; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.coord_axis (
    parameter character varying(16) NOT NULL,
    axis character varying(8) NOT NULL,
    idx integer NOT NULL,
    value real NOT NULL
);


ALTER TABLE public.coord_axis OWNER TO postgres;

--
-- Name: metadata; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.metadata (
    id integer NOT NULL,
    time_step character varying(6) NOT NULL,
    year smallint NOT NULL,
    month smallint NOT NULL,
    parameter character varying(16) NOT NULL,
    parameter_long character varying(128),
    units character varying(32),
    lat_min real NOT NULL,
    lat_max real NOT NULL,
    lon_min real NOT NULL,
    lon_max real NOT NULL,
    n_lat integer NOT NULL,
    n_lon integer NOT NULL,
    tiledb_uri text NOT NULL,
    legacy_npy_path text,
    netcdf_source text,
    fill_value double precision,
    data_min double precision,
    data_max double precision,
    data_mean double precision,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.metadata OWNER TO postgres;

--
-- Name: metadata_v1_legacy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.metadata_v1_legacy (
    id integer NOT NULL,
    time_step text,
    parameter text,
    grid_file text
);


ALTER TABLE public.metadata_v1_legacy OWNER TO postgres;

--
-- Name: metadata_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.metadata_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.metadata_id_seq OWNER TO postgres;

--
-- Name: metadata_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.metadata_id_seq OWNED BY public.metadata_v1_legacy.id;


--
-- Name: metadata_id_seq1; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.metadata_id_seq1
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.metadata_id_seq1 OWNER TO postgres;

--
-- Name: metadata_id_seq1; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.metadata_id_seq1 OWNED BY public.metadata.id;


--
-- Name: query_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.query_log (
    id integer NOT NULL,
    received_at timestamp with time zone DEFAULT now(),
    query_json jsonb,
    plan_json jsonb,
    pg_time_ms real,
    array_time_ms real,
    total_time_ms real,
    result_shape integer[],
    n_files_pruned integer
);


ALTER TABLE public.query_log OWNER TO postgres;

--
-- Name: query_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.query_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.query_log_id_seq OWNER TO postgres;

--
-- Name: query_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.query_log_id_seq OWNED BY public.query_log.id;


--
-- Name: metadata id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metadata ALTER COLUMN id SET DEFAULT nextval('public.metadata_id_seq1'::regclass);


--
-- Name: metadata_v1_legacy id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metadata_v1_legacy ALTER COLUMN id SET DEFAULT nextval('public.metadata_id_seq'::regclass);


--
-- Name: query_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.query_log ALTER COLUMN id SET DEFAULT nextval('public.query_log_id_seq'::regclass);


--
-- Name: coord_axis coord_axis_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.coord_axis
    ADD CONSTRAINT coord_axis_pkey PRIMARY KEY (parameter, axis, idx);


--
-- Name: metadata_v1_legacy metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metadata_v1_legacy
    ADD CONSTRAINT metadata_pkey PRIMARY KEY (id);


--
-- Name: metadata metadata_pkey1; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metadata
    ADD CONSTRAINT metadata_pkey1 PRIMARY KEY (id);


--
-- Name: metadata metadata_time_step_parameter_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metadata
    ADD CONSTRAINT metadata_time_step_parameter_key UNIQUE (time_step, parameter);


--
-- Name: query_log query_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.query_log
    ADD CONSTRAINT query_log_pkey PRIMARY KEY (id);


--
-- Name: idx_coord_value; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_coord_value ON public.coord_axis USING btree (parameter, axis, value);


--
-- Name: idx_metadata_bounds; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_metadata_bounds ON public.metadata USING btree (lat_min, lat_max, lon_min, lon_max);


--
-- Name: idx_metadata_param; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_metadata_param ON public.metadata USING btree (parameter);


--
-- Name: idx_metadata_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_metadata_time ON public.metadata USING btree (time_step);


--
-- Name: idx_metadata_year_mon; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_metadata_year_mon ON public.metadata USING btree (year, month);


--
-- PostgreSQL database dump complete
--

\unrestrict QEIxvU36254NlDnpMseztPk5ARanX9dwhpyxy2SvykDLsUryMklVlfxtapG1lLr

