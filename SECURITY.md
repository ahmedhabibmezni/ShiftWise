# 🔒 Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ Active |

---

## 🛡 Security Architecture

### Authentication

ShiftWise uses **JWT (JSON Web Tokens)** with a stateless access token and a server-tracked refresh token:

| Token Type | Default Expiry | Algorithm | Delivery | Purpose |
|------------|---------------|-----------|----------|---------|
| Access Token | 15 minutes | HS256 | `Authorization: Bearer` header | API request authorization |
| Refresh Token | 7 days | HS256 | `HttpOnly` cookie | Obtain new access tokens without re-login |

- Tokens are signed with a server-side `SECRET_KEY` (configurable via `.env`)
- Token type (`access` / `refresh`) is embedded in the payload to prevent misuse
- The refresh cookie is `HttpOnly; Secure; SameSite=Strict` and scoped to `/api/v1/auth`
- Refresh tokens are tracked in Redis with **family-based rotation**: each use issues a new token and invalidates the previous one; a replayed (reused) token revokes the entire family
- **Brute-force protection** — `/auth/login` enforces a sliding-window lockout (default: 5 failed attempts per 15 minutes), counted per email and per source IP
- Every successful login records an audit trail (`last_login_at`, `last_login_ip`)

### Password Security

| Mechanism | Detail |
|-----------|--------|
| Hashing algorithm | bcrypt (via `passlib`) |
| Max password length | 72 bytes (bcrypt limit, auto-truncated) |
| Minimum requirements | 8 characters, mixed case, at least one digit |
| Storage | Only bcrypt hash stored in PostgreSQL |

### RBAC (Role-Based Access Control)

Access is enforced at the API dependency injection layer (`deps.py`). Every protected endpoint validates:
1. Valid JWT token
2. User exists and is active
3. User's role has the required permission for the requested resource and action

### Multi-Tenancy

- Each user belongs to a `tenant_id` (organization)
- All database queries are scoped to the user's tenant
- Cross-tenant data access is prevented at the CRUD layer
- Only `super_admin` can operate across tenants

### Kubernetes / OpenShift Authentication

| Mode | Use Case | Credential Storage |
|------|----------|-------------------|
| `kubeconfig` | Local development | File at `config/kubeconfig` (gitignored) |
| `incluster` | Production pods | Kubernetes ServiceAccount (auto-mounted) |
| `custom` | External access | API URL + bearer token via environment variables |

- SSL verification is configurable (`KUBERNETES_VERIFY_SSL`)
- The `kubeconfig` file and all tokens are excluded from version control via `.gitignore`

---

## 🚨 Reporting a Vulnerability

If you discover a security vulnerability in ShiftWise, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. **Email:** Contact the maintainer directly at the email associated with the repository
3. **Include:**
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact assessment
   - Suggested fix (if any)

### Response Timeline

| Action | Timeframe |
|--------|-----------|
| Acknowledgment | Within 48 hours |
| Initial assessment | Within 5 business days |
| Fix & disclosure | Coordinated with reporter |

---

## 🔐 Security Best Practices for Deployment

### Environment Variables

```bash
# Generate a strong SECRET_KEY (minimum 32 characters)
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

- **Never** commit `.env` files to version control
- Use the provided `.env.example` as a template
- In production, use OpenShift Secrets or a vault service

### Database

- Use network-level isolation (private subnet)
- Enable PostgreSQL SSL connections in production
- Limit database user privileges to the minimum required
- Regularly back up using `pg_dump`

### OpenShift Cluster

- Restrict API access via network policies
- Use dedicated ServiceAccounts with minimal RBAC bindings
- Keep KubeVirt and OpenShift versions up to date
- Monitor audit logs via OpenShift's built-in logging stack

### General

- Keep all dependencies updated (`pip list --outdated`)
- Run SonarQube scans regularly for code quality and security analysis
- Set `DEBUG=False` in production environments
- Configure CORS to allow only trusted frontend origins

---

## 📄 Dependencies with Security Implications

| Package | Purpose | Security Relevance |
|---------|---------|-------------------|
| `python-jose` | JWT encoding/decoding | Token integrity and expiration |
| `passlib[bcrypt]` | Password hashing | Brute-force resistance |
| `bcrypt` | Hashing backend | Slow hash function by design |
| `pydantic-settings` | Config validation | Prevents misconfiguration |
| `kubernetes` | Cluster API client | ServiceAccount token handling |
| `paramiko` | SSH connections | Remote hypervisor access (KVM/libvirt, Hyper-V) |
| `redis` | Refresh-token store | Token family rotation, reuse detection, login throttle |

---

*This security policy is reviewed and updated with each major release.*