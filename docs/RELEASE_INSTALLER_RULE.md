# Installer distribution rule

Only the installer artifact from the final green `main` Windows build should be distributed for live installation. Earlier candidate installers are superseded after any code, migration, security or installer change. Record the final SHA-256 in the go-live sign-off sheet.
