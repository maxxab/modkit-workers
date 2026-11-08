# Changelog

## Unreleased

- Add reviewed W01 admission and W02/W04 read/find SQL, with private installation
  boundaries and caller-owned native test helpers.
- Add W03 job listing SQL with job-kind filtering before tuple pagination,
  complete-page validation and an Events-owned index guard.
- Keep production migration manifests, runtime grants, public Events dependencies
  and full runtime qualification open; these resources remain NOT_READY.

- Clarify validator type flow while retaining exact runtime checks and failure behavior.

- Normalize source and test formatting with Ruff 0.17.3 and enforce formatting in
  dependency-independent source CI; full dependency and runtime gates remain open.
- Add dependency-independent source CI for lint, selected tests and sdist privacy;
  full dependency and runtime qualification remain blocked.
- Add typed worker contracts, pure persistence models and an inert migration resource reader.
- Production SQL/manifests, worker execution runtime and service qualification remain incomplete.
- Status: NOT_READY for production or package release.
