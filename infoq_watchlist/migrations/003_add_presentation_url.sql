ALTER TABLE talks ADD COLUMN presentation_url TEXT;
UPDATE talks SET presentation_url = url WHERE presentation_url IS NULL;
