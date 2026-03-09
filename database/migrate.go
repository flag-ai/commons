package database

import (
	"fmt"
	"log/slog"

	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/postgres" // postgres driver
	_ "github.com/golang-migrate/migrate/v4/source/file"       // file source
)

// RunMigrations runs database migrations from the given source path.
// sourcePath should be a file:// URL pointing to the migrations directory.
// dbURL should be a postgres:// connection string.
func RunMigrations(sourcePath, dbURL string, logger *slog.Logger) error {
	m, err := migrate.New(sourcePath, dbURL)
	if err != nil {
		return fmt.Errorf("database: failed to create migrator: %w", err)
	}
	defer func() {
		srcErr, dbErr := m.Close()
		if logger != nil {
			if srcErr != nil {
				logger.Warn("failed to close migration source", "error", srcErr)
			}
			if dbErr != nil {
				logger.Warn("failed to close migration database", "error", dbErr)
			}
		}
	}()

	if logger != nil {
		logger.Info("running database migrations", "source", sourcePath)
	}

	if err := m.Up(); err != nil && err != migrate.ErrNoChange {
		return fmt.Errorf("database: migration failed: %w", err)
	}

	ver, dirty, verErr := m.Version()
	if logger != nil {
		if verErr != nil {
			logger.Warn("could not read migration version", "error", verErr)
		} else {
			logger.Info("migrations complete", "version", ver, "dirty", dirty)
		}
	}

	return nil
}
