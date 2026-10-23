-- Esquema de telemetría. Corre una sola vez al crear el volumen de la base.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE telemetria (
  time              timestamptz NOT NULL,
  set_id            text        NOT NULL,
  pump_id           text        NOT NULL,
  stage             int,
  fuel              text,
  pressure_psi      real,
  rate_bpm          real,
  hhp               real,
  engine_rpm        real,
  pump_rpm          real,
  power_end_temp_c  real,
  lube_oil_psi      real,
  vibration_mm_s    real,
  diesel_lph        real,
  gas_m3h           real,
  gas_subst_pct     real,
  fluid_end_hours   real,
  received_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (pump_id, time)  -- evita duplicados cuando el buffer reenvía
);
SELECT create_hypertable('telemetria', by_range('time', INTERVAL '1 day'));
ALTER TABLE telemetria SET (timescaledb.compress, timescaledb.compress_segmentby = 'pump_id');
SELECT add_compression_policy('telemetria', INTERVAL '7 days');
SELECT add_retention_policy('telemetria', INTERVAL '90 days');

-- Agregado continuo por minuto: lo leen el agente y los tableros de rangos largos.
CREATE MATERIALIZED VIEW telemetria_1m WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 minute', time) AS bucket,
       set_id, pump_id,
       avg(pressure_psi)     AS pressure_psi,
       avg(rate_bpm)         AS rate_bpm,
       avg(hhp)              AS hhp,
       avg(power_end_temp_c) AS temp_avg,
       max(power_end_temp_c) AS temp_max,
       avg(lube_oil_psi)     AS oil_avg,
       min(lube_oil_psi)     AS oil_min,
       avg(vibration_mm_s)   AS vib_avg,
       max(vibration_mm_s)   AS vib_max,
       sum(rate_bpm) / nullif(sum(pump_rpm), 0) AS bbl_por_vuelta,
       avg(diesel_lph)       AS diesel_lph,
       avg(gas_m3h)          AS gas_m3h,
       avg(gas_subst_pct)    AS gas_subst_pct,
       max(fluid_end_hours)  AS fluid_end_hours,
       count(*)              AS n
FROM telemetria
GROUP BY bucket, set_id, pump_id
WITH NO DATA;
ALTER MATERIALIZED VIEW telemetria_1m SET (timescaledb.materialized_only = false);
SELECT add_continuous_aggregate_policy('telemetria_1m',
  start_offset => INTERVAL '2 hours', end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');

CREATE TABLE eventos (
  time    timestamptz NOT NULL,
  set_id  text NOT NULL,
  pump_id text,
  tipo    text NOT NULL,
  datos   jsonb
);
CREATE INDEX ON eventos (time DESC);

CREATE TABLE ordenes (
  id                  bigserial PRIMARY KEY,
  created_at          timestamptz NOT NULL DEFAULT now(),
  set_id              text NOT NULL,
  pump_id             text NOT NULL,
  componente          text NOT NULL,
  prioridad           text NOT NULL CHECK (prioridad IN ('alta', 'media', 'baja')),
  motivo              text NOT NULL,
  accion_recomendada  text NOT NULL,
  evidencia           jsonb,
  regla               text,
  estado              text NOT NULL DEFAULT 'propuesta'
                      CHECK (estado IN ('propuesta', 'aprobada', 'rechazada', 'cerrada')),
  creada_por          text NOT NULL DEFAULT 'agente',
  revisada_por        text,
  revisada_at         timestamptz
);
-- Una sola orden abierta por bomba y componente: la base impide duplicados aunque el agente se equivoque.
CREATE UNIQUE INDEX ordenes_abiertas ON ordenes (pump_id, componente) WHERE estado IN ('propuesta', 'aprobada');

CREATE TABLE descartes (
  id          bigserial PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  pump_id     text NOT NULL,
  componente  text NOT NULL,
  motivo      text NOT NULL
);

CREATE TABLE corridas_agente (
  id             bigserial PRIMARY KEY,
  started_at     timestamptz NOT NULL DEFAULT now(),
  modo           text NOT NULL,          -- 'llm' | 'reglas'
  modelo         text,
  candidatos     jsonb,
  acciones       jsonb,
  input_tokens   int,
  output_tokens  int,
  costo_usd      numeric(10, 5),
  duracion_ms    int,
  error          text
);

CREATE TABLE resumenes (
  id          bigserial PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  set_id      text NOT NULL,
  horas       int NOT NULL,
  texto       text NOT NULL,
  modo        text NOT NULL
);

-- Usuario de solo lectura para Grafana.
CREATE ROLE grafana LOGIN PASSWORD 'grafana';
GRANT USAGE ON SCHEMA public TO grafana;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana;
