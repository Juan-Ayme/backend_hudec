    -- schema_clean.sql
    -- Clean, human-readable version of the database schema
    -- Groups tables with their keys, constraints and indexes for easy reading and management.

    -- 1. Departments
    CREATE TABLE departments (
        id SERIAL PRIMARY KEY,
        name VARCHAR(150) UNIQUE NOT NULL,
        slug VARCHAR(180) UNIQUE NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );

    -- 2. Categories
    CREATE TABLE categories (
        id SERIAL PRIMARY KEY,
        department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        slug VARCHAR(230) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        UNIQUE (department_id, name)
    );
    CREATE INDEX idx_categories_department ON categories(department_id);

    -- 3. Subcategories
    CREATE TABLE subcategories (
        id SERIAL PRIMARY KEY,
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        slug VARCHAR(230) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        UNIQUE (category_id, name)
    );
    CREATE INDEX idx_subcategories_category ON subcategories(category_id);

    -- 4. Product Types
    CREATE TABLE product_types (
        bsale_product_type_id INTEGER PRIMARY KEY,
        name VARCHAR(300) NOT NULL,
        subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        is_mapped BOOLEAN DEFAULT FALSE NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_product_types_subcategory ON product_types(subcategory_id);

    -- 5. Products
    CREATE TABLE products (
        bsale_product_id INTEGER PRIMARY KEY,
        name VARCHAR(500) NOT NULL,
        description TEXT,
        bsale_product_type_id INTEGER REFERENCES product_types(bsale_product_type_id) ON DELETE SET NULL,
        subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL,
        stock_control BOOLEAN DEFAULT TRUE NOT NULL,
        allow_decimal BOOLEAN DEFAULT FALSE NOT NULL,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_products_product_type ON products(bsale_product_type_id);

    -- 6. Product Type Attributes
    CREATE TABLE product_type_attributes (
        bsale_attribute_id INTEGER PRIMARY KEY,
        bsale_product_type_id INTEGER REFERENCES product_types(bsale_product_type_id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_ptype_attrs_ptype ON product_type_attributes(bsale_product_type_id);

    -- 7. Variants
    CREATE TABLE variants (
        bsale_variant_id INTEGER PRIMARY KEY,
        bsale_product_id INTEGER REFERENCES products(bsale_product_id) ON DELETE SET NULL,
        code VARCHAR(100),
        bar_code VARCHAR(100),
        display_code VARCHAR(100) NOT NULL,
        description TEXT,
        unit VARCHAR(50),
        allow_negative_stock BOOLEAN DEFAULT FALSE NOT NULL,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_variants_product ON variants(bsale_product_id);
    CREATE INDEX idx_variants_code ON variants(code);
    CREATE INDEX idx_variants_bar_code ON variants(bar_code);

    -- 8. Variant Attribute Values
    CREATE TABLE variant_attribute_values (
        bsale_av_id INTEGER PRIMARY KEY,
        bsale_variant_id INTEGER NOT NULL,
        bsale_attribute_id INTEGER NOT NULL REFERENCES product_type_attributes(bsale_attribute_id) ON DELETE CASCADE,
        description VARCHAR(500) NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        UNIQUE (bsale_variant_id, bsale_attribute_id)
    );
    CREATE INDEX idx_vav_variant ON variant_attribute_values(bsale_variant_id);
    CREATE INDEX idx_vav_attr ON variant_attribute_values(bsale_attribute_id);

    -- 9. Variant Costs
    CREATE TABLE variant_costs (
        bsale_variant_id INTEGER PRIMARY KEY REFERENCES variants(bsale_variant_id) ON DELETE CASCADE,
        average_cost NUMERIC(20,4) DEFAULT 0 NOT NULL,
        latest_cost NUMERIC(20,4) DEFAULT 0 NOT NULL,
        cost_source VARCHAR(20) DEFAULT 'NONE' NOT NULL,
        effective_cost NUMERIC(20,4) DEFAULT 0 NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );

    -- 10. Offices
    CREATE TABLE offices (
        bsale_office_id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        address TEXT,
        district VARCHAR(150),
        city VARCHAR(150),
        country VARCHAR(100) DEFAULT 'Peru',
        is_virtual BOOLEAN DEFAULT FALSE NOT NULL,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );

    -- 11. Stock Levels
    CREATE TABLE stock_levels (
        bsale_stock_id INTEGER PRIMARY KEY,
        bsale_variant_id INTEGER NOT NULL,
        bsale_office_id INTEGER NOT NULL REFERENCES offices(bsale_office_id) ON DELETE CASCADE,
        quantity NUMERIC(20,4) DEFAULT 0 NOT NULL,
        quantity_reserved NUMERIC(20,4) DEFAULT 0 NOT NULL,
        quantity_available NUMERIC(20,4) DEFAULT 0 NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        UNIQUE (bsale_variant_id, bsale_office_id)
    );
    CREATE INDEX idx_stock_levels_variant ON stock_levels(bsale_variant_id);
    CREATE INDEX idx_stock_levels_office ON stock_levels(bsale_office_id);

    -- 12. Stock History
    CREATE TABLE stock_history (
        id SERIAL PRIMARY KEY,
        snapshot_date DATE NOT NULL,
        bsale_variant_id INTEGER NOT NULL,
        bsale_office_id INTEGER NOT NULL,
        quantity NUMERIC(20,4) DEFAULT 0 NOT NULL,
        quantity_reserved NUMERIC(20,4) DEFAULT 0 NOT NULL,
        quantity_available NUMERIC(20,4) DEFAULT 0 NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        UNIQUE (snapshot_date, bsale_variant_id, bsale_office_id)
    );
    CREATE INDEX idx_stock_history_date ON stock_history(snapshot_date);
    CREATE INDEX idx_stock_history_variant ON stock_history(bsale_variant_id);

    -- 13. Document Types
    CREATE TABLE document_types (
        bsale_document_type_id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        code VARCHAR(10),
        is_credit_note BOOLEAN DEFAULT FALSE NOT NULL,
        is_sales_note BOOLEAN DEFAULT FALSE NOT NULL,
        is_electronic BOOLEAN DEFAULT FALSE NOT NULL,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );

    -- 14. Documents
    CREATE TABLE documents (
        bsale_document_id INTEGER PRIMARY KEY,
        bsale_document_type_id INTEGER NOT NULL REFERENCES document_types(bsale_document_type_id),
        bsale_office_id INTEGER REFERENCES offices(bsale_office_id),
        emission_date TIMESTAMPTZ NOT NULL,
        generation_date TIMESTAMPTZ,
        serial_number VARCHAR(50),
        doc_number INTEGER,
        total_amount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        net_amount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        tax_amount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        exempt_amount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        is_credit_note BOOLEAN DEFAULT FALSE NOT NULL,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        bsale_user_id INTEGER,
        token VARCHAR(60),
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_documents_doctype ON documents(bsale_document_type_id);
    CREATE INDEX idx_documents_office ON documents(bsale_office_id);
    CREATE INDEX idx_documents_emission ON documents(emission_date);
    CREATE INDEX idx_documents_credit ON documents(is_credit_note);

    -- 15. Document Details
    CREATE TABLE document_details (
        bsale_detail_id INTEGER PRIMARY KEY,
        bsale_document_id INTEGER NOT NULL REFERENCES documents(bsale_document_id) ON DELETE CASCADE,
        bsale_variant_id INTEGER NOT NULL,
        quantity NUMERIC(20,4) DEFAULT 0 NOT NULL,
        net_unit_value NUMERIC(20,4) DEFAULT 0 NOT NULL,
        net_unit_value_raw NUMERIC(20,4) DEFAULT 0 NOT NULL,
        total_unit_value NUMERIC(20,4) DEFAULT 0 NOT NULL,
        net_amount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        tax_amount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        total_amount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        discount_percentage NUMERIC(6,2) DEFAULT 0 NOT NULL,
        net_discount NUMERIC(20,2) DEFAULT 0 NOT NULL,
        is_gratuity BOOLEAN DEFAULT FALSE NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_doc_details_document ON document_details(bsale_document_id);
    CREATE INDEX idx_doc_details_variant ON document_details(bsale_variant_id);

    -- 16. Receptions
    CREATE TABLE receptions (
        bsale_reception_id INTEGER PRIMARY KEY,
        bsale_office_id INTEGER NOT NULL REFERENCES offices(bsale_office_id) ON DELETE CASCADE,
        admission_date TIMESTAMPTZ NOT NULL,
        admission_date_raw VARCHAR(30),
        document_ref VARCHAR(150),
        document_number VARCHAR(100),
        note TEXT,
        is_internal_dispatch BOOLEAN DEFAULT FALSE NOT NULL,
        is_transfer BOOLEAN DEFAULT FALSE NOT NULL,
        bsale_user_id INTEGER,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_receptions_office ON receptions(bsale_office_id);
    CREATE INDEX idx_receptions_date ON receptions(admission_date);

    -- 17. Reception Details
    CREATE TABLE reception_details (
        bsale_reception_detail_id INTEGER PRIMARY KEY,
        bsale_reception_id INTEGER NOT NULL REFERENCES receptions(bsale_reception_id) ON DELETE CASCADE,
        bsale_variant_id INTEGER NOT NULL,
        quantity NUMERIC(20,4) DEFAULT 0 NOT NULL,
        cost NUMERIC(20,4) DEFAULT 0 NOT NULL,
        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_reception_details_reception ON reception_details(bsale_reception_id);
    CREATE INDEX idx_reception_details_variant ON reception_details(bsale_variant_id);

    -- 18. Consumptions (consumos/mermas registrados en Bsale)
    CREATE TABLE consumptions (
        bsale_consumption_id INTEGER PRIMARY KEY,
        bsale_office_id INTEGER NOT NULL REFERENCES offices(bsale_office_id) ON DELETE CASCADE,
        consumption_date TIMESTAMPTZ NOT NULL,
        note VARCHAR(255),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX idx_consumptions_date ON consumptions(consumption_date);
    CREATE INDEX idx_consumptions_office ON consumptions(bsale_office_id);

    -- 19. Consumption Details
    CREATE TABLE consumption_details (
        id SERIAL PRIMARY KEY,
        bsale_consumption_id INTEGER NOT NULL REFERENCES consumptions(bsale_consumption_id) ON DELETE CASCADE,
        bsale_variant_id INTEGER NOT NULL,
        quantity NUMERIC NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX idx_consumption_details_cons ON consumption_details(bsale_consumption_id);
    CREATE INDEX idx_consumption_details_var ON consumption_details(bsale_variant_id);

    -- 20. Data Quality Issues
    CREATE TABLE data_quality_issues (
        id SERIAL PRIMARY KEY,
        entity VARCHAR(80) NOT NULL,
        bsale_id INTEGER,
        field VARCHAR(120),
        issue_type VARCHAR(60),
        description TEXT,
        raw_value TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_dqi_entity ON data_quality_issues(entity, created_at DESC);

    -- 21. Sync Log
    CREATE TABLE sync_log (
        id SERIAL PRIMARY KEY,
        entity VARCHAR(80) NOT NULL,
        status VARCHAR(20) DEFAULT 'RUNNING' NOT NULL,
        params JSONB,
        records_fetched INTEGER DEFAULT 0 NOT NULL,
        records_inserted INTEGER DEFAULT 0 NOT NULL,
        records_updated INTEGER DEFAULT 0 NOT NULL,
        records_skipped INTEGER DEFAULT 0 NOT NULL,
        error_message TEXT,
        started_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        finished_at TIMESTAMPTZ
    );
    CREATE INDEX idx_sync_log_entity ON sync_log(entity, started_at DESC);

    -- 22. Views
    CREATE VIEW v_product_types_full AS
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
    FROM product_types pt
        LEFT JOIN subcategories s ON s.id = pt.subcategory_id
        LEFT JOIN categories c ON c.id = s.category_id
        LEFT JOIN departments d ON d.id = c.department_id;

    CREATE VIEW v_products_full AS
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
    FROM products p
        LEFT JOIN product_types pt ON p.bsale_product_type_id = pt.bsale_product_type_id
        LEFT JOIN subcategories s ON s.id = COALESCE(p.subcategory_id, pt.subcategory_id)
        LEFT JOIN categories c ON c.id = s.category_id
        LEFT JOIN departments d ON d.id = c.department_id;
