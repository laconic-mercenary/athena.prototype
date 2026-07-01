-- Sarif Industries — sarif_prod database
-- Provisioned by automated deployment pipeline

CREATE TABLE employees (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(50)  NOT NULL UNIQUE,
    email      VARCHAR(100) NOT NULL,
    role       VARCHAR(20)  NOT NULL,
    department VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO employees (username, email, role, department) VALUES
    ('jsmith',   'jsmith@sarif.corp',   'admin',     'IT'),
    ('alee',     'alee@sarif.corp',     'developer', 'Engineering'),
    ('bwilson',  'bwilson@sarif.corp',  'manager',   'Operations'),
    ('cjones',   'cjones@sarif.corp',   'developer', 'Engineering'),
    ('dmartin',  'dmartin@sarif.corp',  'admin',     'IT');

CREATE TABLE api_keys (
    id         SERIAL PRIMARY KEY,
    service    VARCHAR(50)  NOT NULL,
    key_value  VARCHAR(100) NOT NULL,
    active     BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO api_keys (service, key_value, active) VALUES
    ('internal_api',    'ik_prod_a1b2c3d4e5f6', TRUE),
    ('monitoring',      'mk_mon_x9y8z7w6v5u4',  TRUE),
    ('backup_service',  'bk_bkp_deprecated',    FALSE);

CREATE TABLE system_config (
    key         VARCHAR(100) PRIMARY KEY,
    value       TEXT NOT NULL,
    description VARCHAR(200)
);

INSERT INTO system_config (key, value, description) VALUES
    ('smtp_password',         'SarifMail2024!',                'SMTP relay password'),
    ('backup_encryption_key', '4e6f747468696e67546f536565486572', 'AES-256 backup key (hex)'),
    ('admin_recovery_code',   'SARIF-RECOVERY-2024-XK9P',      'Emergency admin recovery code'),
    ('vpn_psk',               'SarifVPN#SharedKey99',           'Site-to-site VPN pre-shared key');
