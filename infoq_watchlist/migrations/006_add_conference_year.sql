-- Conference year is the year of the QCon event a talk was crawled from, which
-- differs from `year` (the InfoQ publication year — videos often go live 1-2
-- years after the event). Storing it lets us browse/report by conference edition.
ALTER TABLE talks ADD COLUMN conference_year INTEGER;

CREATE INDEX IF NOT EXISTS idx_talks_conference_year ON talks(conference_year);
