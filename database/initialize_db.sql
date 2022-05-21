CREATE DATABASE mitwelten
    WITH
    OWNER = postgres
    ENCODING = 'UTF8'
    CONNECTION LIMIT = -1;

CREATE ROLE mitwelten_admin WITH
    LOGIN
    SUPERUSER
    CREATEDB
    CREATEROLE
    INHERIT
    REPLICATION
    CONNECTION LIMIT -1
    -- replace with password
    PASSWORD '***';

CREATE ROLE mitwelten_internal WITH
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    INHERIT
    NOREPLICATION
    CONNECTION LIMIT -1
    -- replace with password
    PASSWORD '***';

CREATE ROLE mitwelten_public WITH
    LOGIN
    NOSUPERUSER
    INHERIT
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    CONNECTION LIMIT -1
    -- replace with password
    PASSWORD '***';

-- tables

CREATE TABLE files
(
    file_id serial,
    original_file_path text NOT NULL,
    sha256 varchar(64),
    disk varchar(64),
    action varchar(32),
    state varchar(32),
    --
    -- created_on timestamp with time zone NOT NULL,
    -- updated_on timestamp with time zone NOT NULL,
    -- uploaded_on timestamp with time zone,
    --
    file_path text,
    file_name text,
    time_start timestamp with time zone,
    time_end timestamp with time zone,
    location point,
    file_size integer,
    format varchar(64),
    sample_rate integer,
    bit_depth smallint,
    channels smallint,
    week varchar(32), -- KW44, KW21_22
    device_id varchar(32), -- 9589-1225, AM1, AM2
    serial_number varchar(32), -- 247475055F2569A5
    battery real,
    temperature real,
    duration double precision,
    gain varchar(32),
    filter varchar(64),
    source varchar(32),
    rec_end_status varchar(32)
    class varchar(32),
    comment varchar(64),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (result_id)
);

CREATE TABLE public.results
(
    result_id serial,
    selection_id bigint NOT NULL,
    file_id bigint NOT NULL,
    object_name text NOT NULL,
    time_start real NOT NULL,
    time_end real NOT NULL,
    confidence real NOT NULL,
    species character varying(255) NOT NULL,
    PRIMARY KEY (result_id)
);

-- grant permissions
ALTER TABLE IF EXISTS public.files
    OWNER to mitwelten_admin;
ALTER TABLE IF EXISTS public.results
    OWNER to mitwelten_admin;

GRANT ALL ON TABLE public.files TO mitwelten_internal;
GRANT ALL ON TABLE public.results TO mitwelten_internal;

GRANT UPDATE ON SEQUENCE public.files_file_id_seq TO mitwelten_internal;
GRANT UPDATE ON SEQUENCE public.results_result_id_seq TO mitwelten_internal;

GRANT SELECT ON TABLE public.files TO mitwelten_public;
GRANT SELECT ON TABLE public.results TO mitwelten_public;
