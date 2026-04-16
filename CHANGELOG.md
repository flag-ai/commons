# Changelog

All notable changes to flag-commons are recorded here.

## 0.2.0

- Add `bonnie` client package. Lifts the BONNIE HTTP client from KARR's
  `internal/bonnie` into a shared package so KARR, KITT, and DEVON all
  consume one implementation. Covers every BONNIE API surface in 0.2.0
  (system, GPU, containers, exec, models, benchmark) plus a reusable
  `Registry` with background health polling.

## 0.1.0

- Initial release: `version`, `secrets`, `logging`, `config`,
  `database`, `health`, and `install` packages.
