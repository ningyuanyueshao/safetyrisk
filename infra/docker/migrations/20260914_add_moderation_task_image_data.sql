-- Existing installations created before image_data was added to schema.sql.
-- Run against the moderation database once; schema.sql covers new databases.
SET @column_exists := (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'moderation_task'
      AND column_name = 'image_data'
);
SET @sql := IF(
    @column_exists = 0,
    'ALTER TABLE moderation_task ADD COLUMN image_data LONGTEXT NULL AFTER image_url',
    'SELECT 1'
);
PREPARE migration_stmt FROM @sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
