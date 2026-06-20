--
-- PostgreSQL database dump
--


-- Dumped from database version 18.1
-- Dumped by pg_dump version 18.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
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
-- Name: categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.categories (
    id integer NOT NULL,
    department_id integer NOT NULL,
    name character varying(200) NOT NULL,
    slug character varying(230) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.categories_id_seq OWNED BY public.categories.id;


--
-- Name: consumption_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumption_details (
    id integer NOT NULL,
    bsale_consumption_id integer NOT NULL,
    bsale_variant_id integer NOT NULL,
    quantity numeric NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: consumption_details_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.consumption_details_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: consumption_details_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.consumption_details_id_seq OWNED BY public.consumption_details.id;


--
-- Name: consumptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumptions (
    bsale_consumption_id integer NOT NULL,
    bsale_office_id integer NOT NULL,
    consumption_date timestamp with time zone NOT NULL,
    note character varying(255),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: data_quality_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_quality_issues (
    id bigint NOT NULL,
    entity character varying(80) NOT NULL,
    bsale_id integer,
    field character varying(120),
    issue_type character varying(60),
    description text,
    raw_value text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: data_quality_issues_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_quality_issues_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_quality_issues_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_quality_issues_id_seq OWNED BY public.data_quality_issues.id;


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    id integer NOT NULL,
    name character varying(150) NOT NULL,
    slug character varying(180) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: departments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.departments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: departments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.departments_id_seq OWNED BY public.departments.id;


--
-- Name: document_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_details (
    bsale_detail_id integer NOT NULL,
    bsale_document_id integer NOT NULL,
    bsale_variant_id integer NOT NULL,
    quantity numeric(20,4) DEFAULT 0 NOT NULL,
    net_unit_value numeric(20,4) DEFAULT 0 NOT NULL,
    net_unit_value_raw numeric(20,4) DEFAULT 0 NOT NULL,
    total_unit_value numeric(20,4) DEFAULT 0 NOT NULL,
    net_amount numeric(20,2) DEFAULT 0 NOT NULL,
    tax_amount numeric(20,2) DEFAULT 0 NOT NULL,
    total_amount numeric(20,2) DEFAULT 0 NOT NULL,
    discount_percentage numeric(6,2) DEFAULT 0 NOT NULL,
    net_discount numeric(20,2) DEFAULT 0 NOT NULL,
    is_gratuity boolean DEFAULT false NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: document_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_types (
    bsale_document_type_id integer NOT NULL,
    name character varying(200) NOT NULL,
    code character varying(10),
    is_credit_note boolean DEFAULT false NOT NULL,
    is_sales_note boolean DEFAULT false NOT NULL,
    is_electronic boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    bsale_document_id integer NOT NULL,
    bsale_document_type_id integer NOT NULL,
    bsale_office_id integer,
    emission_date timestamp with time zone NOT NULL,
    generation_date timestamp with time zone,
    serial_number character varying(50),
    doc_number integer,
    total_amount numeric(20,2) DEFAULT 0 NOT NULL,
    net_amount numeric(20,2) DEFAULT 0 NOT NULL,
    tax_amount numeric(20,2) DEFAULT 0 NOT NULL,
    exempt_amount numeric(20,2) DEFAULT 0 NOT NULL,
    is_credit_note boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    bsale_user_id integer,
    token character varying(60),
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: offices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.offices (
    bsale_office_id integer NOT NULL,
    name character varying(200) NOT NULL,
    address text,
    district character varying(150),
    city character varying(150),
    country character varying(100) DEFAULT 'Peru'::character varying,
    is_virtual boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: product_type_attributes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.product_type_attributes (
    bsale_attribute_id integer NOT NULL,
    bsale_product_type_id integer,
    name character varying(200) NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: product_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.product_types (
    bsale_product_type_id integer NOT NULL,
    name character varying(300) NOT NULL,
    subcategory_id integer,
    is_active boolean DEFAULT true NOT NULL,
    is_mapped boolean DEFAULT false NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.products (
    bsale_product_id integer NOT NULL,
    name character varying(500) NOT NULL,
    description text,
    bsale_product_type_id integer,
    subcategory_id integer,
    stock_control boolean DEFAULT true NOT NULL,
    allow_decimal boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: reception_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reception_details (
    bsale_reception_detail_id integer NOT NULL,
    bsale_reception_id integer NOT NULL,
    bsale_variant_id integer NOT NULL,
    quantity numeric(20,4) DEFAULT 0 NOT NULL,
    cost numeric(20,4) DEFAULT 0 NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: receptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.receptions (
    bsale_reception_id integer NOT NULL,
    bsale_office_id integer NOT NULL,
    admission_date timestamp with time zone NOT NULL,
    admission_date_raw character varying(30),
    document_ref character varying(150),
    document_number character varying(100),
    note text,
    is_internal_dispatch boolean DEFAULT false NOT NULL,
    is_transfer boolean DEFAULT false NOT NULL,
    bsale_user_id integer,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: stock_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stock_history (
    id bigint NOT NULL,
    snapshot_date date NOT NULL,
    bsale_variant_id integer NOT NULL,
    bsale_office_id integer NOT NULL,
    quantity numeric(20,4) DEFAULT 0 NOT NULL,
    quantity_reserved numeric(20,4) DEFAULT 0 NOT NULL,
    quantity_available numeric(20,4) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: stock_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.stock_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stock_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.stock_history_id_seq OWNED BY public.stock_history.id;


--
-- Name: stock_levels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stock_levels (
    bsale_stock_id integer NOT NULL,
    bsale_variant_id integer NOT NULL,
    bsale_office_id integer NOT NULL,
    quantity numeric(20,4) DEFAULT 0 NOT NULL,
    quantity_reserved numeric(20,4) DEFAULT 0 NOT NULL,
    quantity_available numeric(20,4) DEFAULT 0 NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: subcategories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subcategories (
    id integer NOT NULL,
    category_id integer NOT NULL,
    name character varying(200) NOT NULL,
    slug character varying(230) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: subcategories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.subcategories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: subcategories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.subcategories_id_seq OWNED BY public.subcategories.id;


--
-- Name: sync_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sync_log (
    id integer NOT NULL,
    entity character varying(80) NOT NULL,
    status character varying(20) DEFAULT 'RUNNING'::character varying NOT NULL,
    params jsonb,
    records_fetched integer DEFAULT 0 NOT NULL,
    records_inserted integer DEFAULT 0 NOT NULL,
    records_updated integer DEFAULT 0 NOT NULL,
    records_skipped integer DEFAULT 0 NOT NULL,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone
);


--
-- Name: sync_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sync_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sync_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sync_log_id_seq OWNED BY public.sync_log.id;


--
-- Name: v_product_types_full; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_product_types_full AS
 SELECT pt.bsale_product_type_id,
    pt.name AS product_type_name,
    pt.is_active,
    pt.is_mapped,
    s.id AS subcategory_id,
    s.name AS subcategory,
    c.id AS category_id,
    c.name AS category,
    d.id AS department_id,
    d.name AS department
   FROM (((public.product_types pt
     LEFT JOIN public.subcategories s ON ((s.id = pt.subcategory_id)))
     LEFT JOIN public.categories c ON ((c.id = s.category_id)))
     LEFT JOIN public.departments d ON ((d.id = c.department_id)));


--
-- Name: v_products_full; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_products_full AS
 SELECT p.bsale_product_id,
    p.name AS product_name,
    p.is_active,
    pt.bsale_product_type_id,
    pt.name AS product_type_name,
    pt.is_mapped,
    (p.subcategory_id IS NOT NULL) AS has_override,
    s.name AS subcategory,
    c.name AS category,
    d.name AS department
   FROM ((((public.products p
     LEFT JOIN public.product_types pt ON ((p.bsale_product_type_id = pt.bsale_product_type_id)))
     LEFT JOIN public.subcategories s ON ((s.id = COALESCE(p.subcategory_id, pt.subcategory_id))))
     LEFT JOIN public.categories c ON ((c.id = s.category_id)))
     LEFT JOIN public.departments d ON ((d.id = c.department_id)));


--
-- Name: variant_attribute_values; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.variant_attribute_values (
    bsale_av_id integer NOT NULL,
    bsale_variant_id integer NOT NULL,
    bsale_attribute_id integer NOT NULL,
    description character varying(500) NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: variant_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.variant_costs (
    bsale_variant_id integer NOT NULL,
    average_cost numeric(20,4) DEFAULT 0 NOT NULL,
    latest_cost numeric(20,4) DEFAULT 0 NOT NULL,
    cost_source character varying(20) DEFAULT 'NONE'::character varying NOT NULL,
    effective_cost numeric(20,4) DEFAULT 0 NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: variants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.variants (
    bsale_variant_id integer NOT NULL,
    bsale_product_id integer,
    code character varying(100),
    bar_code character varying(100),
    display_code character varying(100) NOT NULL,
    description text,
    unit character varying(50),
    allow_negative_stock boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.categories ALTER COLUMN id SET DEFAULT nextval('public.categories_id_seq'::regclass);


--
-- Name: consumption_details id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumption_details ALTER COLUMN id SET DEFAULT nextval('public.consumption_details_id_seq'::regclass);


--
-- Name: data_quality_issues id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_issues ALTER COLUMN id SET DEFAULT nextval('public.data_quality_issues_id_seq'::regclass);


--
-- Name: departments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments ALTER COLUMN id SET DEFAULT nextval('public.departments_id_seq'::regclass);


--
-- Name: stock_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_history ALTER COLUMN id SET DEFAULT nextval('public.stock_history_id_seq'::regclass);


--
-- Name: subcategories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subcategories ALTER COLUMN id SET DEFAULT nextval('public.subcategories_id_seq'::regclass);


--
-- Name: sync_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_log ALTER COLUMN id SET DEFAULT nextval('public.sync_log_id_seq'::regclass);


--
-- Name: categories categories_department_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_department_id_name_key UNIQUE (department_id, name);


--
-- Name: categories categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (id);


--
-- Name: consumption_details consumption_details_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumption_details
    ADD CONSTRAINT consumption_details_pkey PRIMARY KEY (id);


--
-- Name: consumptions consumptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumptions
    ADD CONSTRAINT consumptions_pkey PRIMARY KEY (bsale_consumption_id);


--
-- Name: data_quality_issues data_quality_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_issues
    ADD CONSTRAINT data_quality_issues_pkey PRIMARY KEY (id);


--
-- Name: departments departments_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_name_key UNIQUE (name);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (id);


--
-- Name: departments departments_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_slug_key UNIQUE (slug);


--
-- Name: document_details document_details_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_details
    ADD CONSTRAINT document_details_pkey PRIMARY KEY (bsale_detail_id);


--
-- Name: document_types document_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_types
    ADD CONSTRAINT document_types_pkey PRIMARY KEY (bsale_document_type_id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (bsale_document_id);


--
-- Name: offices offices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.offices
    ADD CONSTRAINT offices_pkey PRIMARY KEY (bsale_office_id);


--
-- Name: product_type_attributes product_type_attributes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_type_attributes
    ADD CONSTRAINT product_type_attributes_pkey PRIMARY KEY (bsale_attribute_id);


--
-- Name: product_types product_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_types
    ADD CONSTRAINT product_types_pkey PRIMARY KEY (bsale_product_type_id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (bsale_product_id);


--
-- Name: reception_details reception_details_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reception_details
    ADD CONSTRAINT reception_details_pkey PRIMARY KEY (bsale_reception_detail_id);


--
-- Name: receptions receptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.receptions
    ADD CONSTRAINT receptions_pkey PRIMARY KEY (bsale_reception_id);


--
-- Name: stock_history stock_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_history
    ADD CONSTRAINT stock_history_pkey PRIMARY KEY (id);


--
-- Name: stock_history stock_history_snapshot_date_bsale_variant_id_bsale_office_i_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_history
    ADD CONSTRAINT stock_history_snapshot_date_bsale_variant_id_bsale_office_i_key UNIQUE (snapshot_date, bsale_variant_id, bsale_office_id);


--
-- Name: stock_levels stock_levels_bsale_variant_id_bsale_office_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_levels
    ADD CONSTRAINT stock_levels_bsale_variant_id_bsale_office_id_key UNIQUE (bsale_variant_id, bsale_office_id);


--
-- Name: stock_levels stock_levels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_levels
    ADD CONSTRAINT stock_levels_pkey PRIMARY KEY (bsale_stock_id);


--
-- Name: subcategories subcategories_category_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subcategories
    ADD CONSTRAINT subcategories_category_id_name_key UNIQUE (category_id, name);


--
-- Name: subcategories subcategories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subcategories
    ADD CONSTRAINT subcategories_pkey PRIMARY KEY (id);


--
-- Name: sync_log sync_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_log
    ADD CONSTRAINT sync_log_pkey PRIMARY KEY (id);


--
-- Name: variant_attribute_values variant_attribute_values_bsale_variant_id_bsale_attribute_i_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.variant_attribute_values
    ADD CONSTRAINT variant_attribute_values_bsale_variant_id_bsale_attribute_i_key UNIQUE (bsale_variant_id, bsale_attribute_id);


--
-- Name: variant_attribute_values variant_attribute_values_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.variant_attribute_values
    ADD CONSTRAINT variant_attribute_values_pkey PRIMARY KEY (bsale_av_id);


--
-- Name: variant_costs variant_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.variant_costs
    ADD CONSTRAINT variant_costs_pkey PRIMARY KEY (bsale_variant_id);


--
-- Name: variants variants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.variants
    ADD CONSTRAINT variants_pkey PRIMARY KEY (bsale_variant_id);


--
-- Name: idx_categories_department; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_categories_department ON public.categories USING btree (department_id);


--
-- Name: idx_consumption_details_cons; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consumption_details_cons ON public.consumption_details USING btree (bsale_consumption_id);


--
-- Name: idx_consumption_details_var; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consumption_details_var ON public.consumption_details USING btree (bsale_variant_id);


--
-- Name: idx_consumptions_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consumptions_date ON public.consumptions USING btree (consumption_date);


--
-- Name: idx_consumptions_office; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_consumptions_office ON public.consumptions USING btree (bsale_office_id);


--
-- Name: idx_doc_details_document; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doc_details_document ON public.document_details USING btree (bsale_document_id);


--
-- Name: idx_doc_details_variant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doc_details_variant ON public.document_details USING btree (bsale_variant_id);


--
-- Name: idx_documents_credit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_credit ON public.documents USING btree (is_credit_note);


--
-- Name: idx_documents_doctype; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_doctype ON public.documents USING btree (bsale_document_type_id);


--
-- Name: idx_documents_emission; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_emission ON public.documents USING btree (emission_date);


--
-- Name: idx_documents_office; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_office ON public.documents USING btree (bsale_office_id);


--
-- Name: idx_dqi_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dqi_entity ON public.data_quality_issues USING btree (entity, created_at DESC);


--
-- Name: idx_product_types_subcategory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_product_types_subcategory ON public.product_types USING btree (subcategory_id);


--
-- Name: idx_products_product_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_product_type ON public.products USING btree (bsale_product_type_id);


--
-- Name: idx_ptype_attrs_ptype; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ptype_attrs_ptype ON public.product_type_attributes USING btree (bsale_product_type_id);


--
-- Name: idx_reception_details_reception; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reception_details_reception ON public.reception_details USING btree (bsale_reception_id);


--
-- Name: idx_reception_details_variant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reception_details_variant ON public.reception_details USING btree (bsale_variant_id);


--
-- Name: idx_receptions_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_receptions_date ON public.receptions USING btree (admission_date);


--
-- Name: idx_receptions_office; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_receptions_office ON public.receptions USING btree (bsale_office_id);


--
-- Name: idx_stock_history_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_history_date ON public.stock_history USING btree (snapshot_date);


--
-- Name: idx_stock_history_variant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_history_variant ON public.stock_history USING btree (bsale_variant_id);


--
-- Name: idx_stock_levels_office; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_levels_office ON public.stock_levels USING btree (bsale_office_id);


--
-- Name: idx_stock_levels_variant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_levels_variant ON public.stock_levels USING btree (bsale_variant_id);


--
-- Name: idx_subcategories_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subcategories_category ON public.subcategories USING btree (category_id);


--
-- Name: idx_sync_log_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sync_log_entity ON public.sync_log USING btree (entity, started_at DESC);


--
-- Name: idx_variants_bar_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_variants_bar_code ON public.variants USING btree (bar_code);


--
-- Name: idx_variants_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_variants_code ON public.variants USING btree (code);


--
-- Name: idx_variants_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_variants_product ON public.variants USING btree (bsale_product_id);


--
-- Name: idx_vav_attr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vav_attr ON public.variant_attribute_values USING btree (bsale_attribute_id);


--
-- Name: idx_vav_variant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vav_variant ON public.variant_attribute_values USING btree (bsale_variant_id);


--
-- Name: categories categories_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE CASCADE;


--
-- Name: consumption_details consumption_details_bsale_consumption_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumption_details
    ADD CONSTRAINT consumption_details_bsale_consumption_id_fkey FOREIGN KEY (bsale_consumption_id) REFERENCES public.consumptions(bsale_consumption_id) ON DELETE CASCADE;


--
-- Name: consumptions consumptions_bsale_office_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumptions
    ADD CONSTRAINT consumptions_bsale_office_id_fkey FOREIGN KEY (bsale_office_id) REFERENCES public.offices(bsale_office_id) ON DELETE CASCADE;


--
-- Name: document_details document_details_bsale_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_details
    ADD CONSTRAINT document_details_bsale_document_id_fkey FOREIGN KEY (bsale_document_id) REFERENCES public.documents(bsale_document_id) ON DELETE CASCADE;


--
-- Name: documents documents_bsale_document_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_bsale_document_type_id_fkey FOREIGN KEY (bsale_document_type_id) REFERENCES public.document_types(bsale_document_type_id);


--
-- Name: documents documents_bsale_office_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_bsale_office_id_fkey FOREIGN KEY (bsale_office_id) REFERENCES public.offices(bsale_office_id);


--
-- Name: product_type_attributes product_type_attributes_bsale_product_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_type_attributes
    ADD CONSTRAINT product_type_attributes_bsale_product_type_id_fkey FOREIGN KEY (bsale_product_type_id) REFERENCES public.product_types(bsale_product_type_id) ON DELETE CASCADE;


--
-- Name: product_types product_types_subcategory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_types
    ADD CONSTRAINT product_types_subcategory_id_fkey FOREIGN KEY (subcategory_id) REFERENCES public.subcategories(id) ON DELETE SET NULL;


--
-- Name: products products_bsale_product_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_bsale_product_type_id_fkey FOREIGN KEY (bsale_product_type_id) REFERENCES public.product_types(bsale_product_type_id) ON DELETE SET NULL;


--
-- Name: products products_subcategory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_subcategory_id_fkey FOREIGN KEY (subcategory_id) REFERENCES public.subcategories(id) ON DELETE SET NULL;


--
-- Name: reception_details reception_details_bsale_reception_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reception_details
    ADD CONSTRAINT reception_details_bsale_reception_id_fkey FOREIGN KEY (bsale_reception_id) REFERENCES public.receptions(bsale_reception_id) ON DELETE CASCADE;


--
-- Name: receptions receptions_bsale_office_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.receptions
    ADD CONSTRAINT receptions_bsale_office_id_fkey FOREIGN KEY (bsale_office_id) REFERENCES public.offices(bsale_office_id) ON DELETE CASCADE;


--
-- Name: stock_levels stock_levels_bsale_office_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_levels
    ADD CONSTRAINT stock_levels_bsale_office_id_fkey FOREIGN KEY (bsale_office_id) REFERENCES public.offices(bsale_office_id) ON DELETE CASCADE;


--
-- Name: subcategories subcategories_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subcategories
    ADD CONSTRAINT subcategories_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.categories(id) ON DELETE CASCADE;


--
-- Name: variant_attribute_values variant_attribute_values_bsale_attribute_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.variant_attribute_values
    ADD CONSTRAINT variant_attribute_values_bsale_attribute_id_fkey FOREIGN KEY (bsale_attribute_id) REFERENCES public.product_type_attributes(bsale_attribute_id) ON DELETE CASCADE;


--
-- Name: variant_costs variant_costs_bsale_variant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.variant_costs
    ADD CONSTRAINT variant_costs_bsale_variant_id_fkey FOREIGN KEY (bsale_variant_id) REFERENCES public.variants(bsale_variant_id) ON DELETE CASCADE;


--
-- Name: variants variants_bsale_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.variants
    ADD CONSTRAINT variants_bsale_product_id_fkey FOREIGN KEY (bsale_product_id) REFERENCES public.products(bsale_product_id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--


