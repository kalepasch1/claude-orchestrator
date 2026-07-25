# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email: kale@heretomorrow.us

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix timeline**: Depends on severity, typically within 30 days

## Scope

This policy covers:

- The orchestrator control plane (Python backend)
- The dashboard (Nuxt/Vercel frontend)
- The runner agent system
- API key and credential handling
- Supabase backend configuration

## Supported Versions

Only the latest version on the `master` branch is supported with security updates.

## Security Best Practices for Users

- Never commit API keys or secrets to version control
- Use environment variables for all sensitive configuration
- Rotate Anthropic API keys regularly
- Enable row-level security (RLS) on all Supabase tables
- Review spend limits and approval thresholds regularly
