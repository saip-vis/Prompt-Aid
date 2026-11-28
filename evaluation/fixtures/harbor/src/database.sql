-- Database table and index for analytics events; query performance and aggregation.
CREATE TABLE events (id INTEGER, category TEXT, created_at TEXT);
CREATE INDEX event_category ON events(category);
