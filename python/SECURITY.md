# Security Improvements & Best Practices

This document details the security improvements made to the unistax backend and provides best practices for secure usage.

## Recent Security Fixes

### 1. Password Hashing (CRITICAL FIX)

**Issue:** Previously used SHA256 for password hashing, which is vulnerable to brute-force attacks.

**Fix:** Migrated to bcrypt with configurable work factor.

**File:** `python/src/unistax/security/password.py`

**Changes:**
- ✅ Replaced SHA256 with bcrypt (industry standard)
- ✅ Added automatic salting (bcrypt built-in)
- ✅ Configurable work factor (default: 12 rounds ~300ms)
- ✅ Timing-attack resistant verification
- ✅ Secure fallback with warnings if bcrypt unavailable

**Usage:**
```python
from unistax.security.password import PasswordHasher

# Create hasher with default settings (12 rounds)
hasher = PasswordHasher()

# Hash a password
hashed = hasher.hash("user-password")
# Returns: $2b$12$xxxxx... (bcrypt format)

# Verify password
is_valid = hasher.verify("user-password", hashed)  # True

# Increase work factor for high-security scenarios
secure_hasher = PasswordHasher(rounds=14)  # ~1.2 seconds per hash
```

**Security Notes:**
- Default 12 rounds provides good security/performance balance
- Increase rounds as hardware improves (add 1 every ~18 months)
- Never use rounds < 10 in production
- bcrypt automatically handles salting and timing attacks

**Migration from SHA256:**
```python
# Old hashes will still verify correctly using fallback
# Detect old format and re-hash on next login:

if hasher.verify(password, old_hash):
    if old_hash.startswith("sha256$"):
        # Re-hash with bcrypt
        new_hash = hasher.hash(password)
        # Update database with new_hash
```

---

### 2. SQL Injection Prevention (CRITICAL FIX)

**Issue:** Query builder allowed arbitrary attribute access via `getattr()`, enabling SQL injection and code execution.

**Fix:** Comprehensive input validation and whitelisting.

**File:** `python/src/unistax/query/builder.py`

**Changes:**
- ✅ Field name validation (alphanumeric + underscore only)
- ✅ Operator whitelist (prevents SQL injection)
- ✅ Column existence validation against model
- ✅ Blocked access to private attributes (`__xxx__`)
- ✅ Pagination parameter validation
- ✅ Sort direction validation

**Security Features:**

1. **Field Name Validation:**
```python
# Blocks dangerous inputs
query.where("__class__", "eq", "value")  # ❌ ValueError
query.where("_private", "eq", "value")    # ❌ ValueError
query.where("user'; DROP TABLE--", "eq", "x")  # ❌ ValueError
query.where("user_id", "eq", 123)        # ✅ Valid
```

2. **Operator Whitelist:**
```python
# Only safe operators allowed
ALLOWED_OPERATORS = {
    "eq", "ne", "gt", "gte", "lt", "lte",
    "in", "not_in", "like", "ilike"
}

query.where("email", "DROP", "x")  # ❌ ValueError
query.where("email", "eq", "test@example.com")  # ✅ Valid
```

3. **Column Validation:**
```python
# Only actual model columns can be queried
query.where("nonexistent_field", "eq", "x")  # ❌ ValueError
# Checks against model.__table__.columns
```

**Usage:**
```python
from unistax.query.builder import QueryBuilder

# Safe query building
query = (QueryBuilder()
    .where("user_id", "eq", 123)          # ✅ Validated
    .where("status", "in", ["active"])    # ✅ Safe
    .order_by("created_at", "desc")       # ✅ Validated
    .limit(100)                           # ✅ Range checked
    .offset(0))                           # ✅ Non-negative

# Apply to SQLAlchemy query
results = query.apply_to_sqlalchemy(db_query, UserModel)
```

---

### 3. Security Headers Implementation (FEATURE ADDED)

**Feature:** Added comprehensive OWASP-recommended security headers middleware.

**File:** `python/src/unistax/middleware/builtin.py`

**Changes:**
- ✅ Added SecurityHeadersMiddleware with configurable headers
- ✅ Content-Security-Policy (CSP) with restrictive defaults
- ✅ HTTP Strict Transport Security (HSTS)
- ✅ X-Frame-Options (clickjacking protection)
- ✅ X-Content-Type-Options (MIME sniffing protection)
- ✅ Referrer-Policy
- ✅ Permissions-Policy (feature policy)
- ✅ X-XSS-Protection (legacy browser support)

**Security Headers Included:**

1. **Content-Security-Policy (CSP)**
   - Prevents XSS, data injection, and code execution attacks
   - Default: Restrictive policy allowing only same-origin resources
   - Customizable per application needs

2. **Strict-Transport-Security (HSTS)**
   - Forces HTTPS connections
   - Default: 1 year max-age with includeSubDomains
   - Prevents man-in-the-middle attacks

3. **X-Frame-Options**
   - Prevents clickjacking attacks
   - Default: DENY (no framing allowed)
   - Can be set to SAMEORIGIN if needed

4. **X-Content-Type-Options**
   - Prevents MIME type sniffing
   - Default: nosniff

5. **Referrer-Policy**
   - Controls referrer information leakage
   - Default: strict-origin-when-cross-origin

6. **Permissions-Policy**
   - Disables sensitive browser features
   - Default: Disables geolocation, camera, microphone, etc.

**Usage:**

```python
from unistax.middleware import SecurityHeadersMiddleware, MiddlewarePipeline

# Production configuration with custom CSP
security = SecurityHeadersMiddleware(
    content_security_policy=(
        "default-src 'self'; "
        "script-src 'self' https://cdn.example.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://api.example.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    strict_transport_security="max-age=63072000; includeSubDomains; preload",
    x_frame_options="DENY",
)

# Add to middleware pipeline
pipeline = MiddlewarePipeline()
pipeline.use(security)
```

**Development Configuration:**

```python
# More permissive for local development
security = SecurityHeadersMiddleware(
    content_security_policy=(
        "default-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' ws: wss:"  # Allow WebSocket for hot reload
    ),
    strict_transport_security=None,  # Disable HSTS for HTTP dev server
)
```

**Testing Your Security Headers:**

Use these tools to validate your configuration:
- [https://securityheaders.com/](https://securityheaders.com/)
- [https://observatory.mozilla.org/](https://observatory.mozilla.org/)

**CSP Testing:**

Start with CSP in report-only mode to test without blocking:
```python
security = SecurityHeadersMiddleware(
    custom_headers={
        "Content-Security-Policy-Report-Only": "default-src 'self'; report-uri /csp-report"
    }
)
```

**Security Notes:**
- Customize CSP based on your application's resource loading needs
- Only enable HSTS over HTTPS (causes errors on HTTP)
- Test thoroughly before deploying to production
- Use security scanners to validate configuration
- Consider adding CSP reporting endpoint for violations

---

### 4. Rate Limiting Implementation (FEATURE ADDED)

**Feature:** Added comprehensive rate limiting middleware to prevent brute force attacks and API abuse.

**Files:**
- `python/src/unistax/ratelimit/limiter.py` - Enhanced rate limiter (386 lines)
- `python/src/unistax/ratelimit/middleware.py` - HTTP middleware (NEW, 234 lines)
- `python/src/unistax/ratelimit/storage.py` - Storage backends (NEW, 79 lines)

**Changes:**
- ✅ Enhanced RateLimiter with comprehensive exception handling
- ✅ Added `RateLimitExceeded` exception with detailed context
- ✅ Added `RateLimitInfo` dataclass for status tracking
- ✅ Implemented RateLimitMiddleware for HTTP requests
- ✅ Added InMemoryStorage for single-server deployments
- ✅ Added RedisStorage for distributed systems
- ✅ Standard rate limit headers (X-RateLimit-*)
- ✅ Comprehensive logging for security monitoring
- ✅ Reset and clear methods for limit management

**Security Features:**

1. **Prevents Brute Force Attacks**
   - Configurable limits per endpoint/user/IP
   - Automatic blocking after threshold
   - Exponential backoff via Retry-After header

2. **Standard HTTP Headers**
   - `X-RateLimit-Limit`: Maximum requests allowed
   - `X-RateLimit-Remaining`: Remaining requests in window
   - `X-RateLimit-Reset`: Unix timestamp when limit resets
   - `Retry-After`: Seconds to wait before retrying (when exceeded)

3. **Flexible Key Functions**
   - Per-IP rate limiting (default)
   - Per-user rate limiting
   - Per-endpoint rate limiting
   - Custom key extraction

4. **Multiple Storage Backends**
   - In-memory (single server)
   - Redis (distributed systems)
   - Pluggable architecture for custom backends

**Usage Examples:**

**Basic Rate Limiting:**
```python
from unistax.ratelimit import RateLimiter, RateLimitMiddleware
from unistax.middleware import MiddlewarePipeline

# Create rate limiter: 100 requests per minute
limiter = RateLimiter(limit=100, window=60)

# Add to middleware pipeline
middleware = RateLimitMiddleware(limiter)
pipeline = MiddlewarePipeline()
pipeline.use(middleware)
```

**Protect Authentication Endpoints:**
```python
from unistax.ratelimit import RateLimiter, RateLimitExceeded

# Strict rate limit for login: 5 attempts per 5 minutes
auth_limiter = RateLimiter(limit=5, window=300)

@app.post("/login")
@auth_limiter.limit(key_func=lambda username: f"login:{username}")
async def login(username: str, password: str):
    # Login logic here
    return {"token": "..."}
```

**Per-User Rate Limiting:**
```python
def get_user_key(request):
    user_id = request.context.get("user_id")
    if user_id:
        return f"user:{user_id}"
    # Fallback to IP if not authenticated
    return f"ip:{request.headers.get('X-Real-IP', 'unknown')}"

middleware = RateLimitMiddleware(limiter, key_func=get_user_key)
```

**Distributed Rate Limiting (Redis):**
```python
from unistax.ratelimit import RateLimiter, RedisStorage

# Use Redis for distributed systems
storage = RedisStorage(host="localhost", port=6379)
limiter = RateLimiter(limit=1000, window=60, storage=storage)
```

**Custom Rate Limits by Endpoint:**
```python
# Different limits for different endpoints
api_limiter = RateLimiter(limit=1000, window=60)      # 1000 req/min
auth_limiter = RateLimiter(limit=5, window=300)       # 5 req/5min
upload_limiter = RateLimiter(limit=10, window=3600)   # 10 req/hour

@app.post("/api/data")
@api_limiter.limit(key_func=lambda req: f"api:{req.context.get('user_id')}")
async def get_data():
    pass

@app.post("/auth/login")
@auth_limiter.limit(key_func=lambda req: f"login:{req.body.get('username')}")
async def login():
    pass

@app.post("/upload")
@upload_limiter.limit(key_func=lambda req: f"upload:{req.context.get('user_id')}")
async def upload_file():
    pass
```

**Exception Handling:**
```python
from unistax.ratelimit import RateLimitExceeded

try:
    info = limiter.check_limit("user:123")
    # Process request
except RateLimitExceeded as e:
    # Return 429 Too Many Requests
    return {
        "error": "Rate limit exceeded",
        "retry_after": e.retry_after,
        "limit": e.limit,
        "window": e.window
    }
```

**Recommended Limits by Endpoint Type:**

| Endpoint Type | Limit | Window | Rationale |
|--------------|-------|---------|-----------|
| Authentication (login) | 5-10 | 5-15 min | Prevent brute force |
| Password reset | 3-5 | 15-60 min | Prevent enumeration |
| Registration | 5 | 60 min | Prevent spam accounts |
| API endpoints (authenticated) | 100-1000 | 60 sec | Prevent abuse |
| API endpoints (public) | 10-100 | 60 sec | Prevent DoS |
| File uploads | 10-20 | 3600 sec | Prevent resource exhaustion |
| Search endpoints | 50-100 | 60 sec | Prevent expensive queries |

**Security Best Practices:**
- Always use rate limiting on authentication endpoints
- Use stricter limits for sensitive operations
- Log rate limit violations for security monitoring
- Use Redis storage for distributed deployments
- Reset limits after successful 2FA/verification
- Consider IP + user combined limits for better protection
- Monitor rate limit metrics for attack detection

**Testing Rate Limits:**
```python
# Get current limit status
info = limiter.get_limit_info("user:123")
print(f"Remaining: {info.remaining}/{info.limit}")
print(f"Resets at: {info.reset}")

# Reset limit (e.g., after successful 2FA)
limiter.reset("login:user:123")

# Clear all limits (testing only!)
limiter.clear_all()
```

---

### 5. CSRF Protection Implementation (FEATURE ADDED)

**Feature:** Added Cross-Site Request Forgery (CSRF) protection middleware using double-submit cookie pattern.

**Files:**
- `python/src/unistax/csrf/protect.py` - Core CSRF protection with token generation/validation
- `python/src/unistax/csrf/middleware.py` - HTTP middleware integration
- `python/src/unistax/csrf/exceptions.py` - CSRF-specific exceptions
- `python/src/unistax/csrf/__init__.py` - Module exports

**Security Features:**
- **Double-submit cookie pattern** - Stateless CSRF protection (no server-side session required)
- **Cryptographically secure tokens** - Uses secrets.token_urlsafe() for token generation
- **HMAC signature validation** - Prevents token forgery with secret-based signatures
- **Token expiration** - Optional time-based token expiration
- **User binding** - Optional user-specific tokens for additional security
- **Constant-time comparison** - Prevents timing attacks during validation
- **Exempt endpoints** - Configurable patterns for webhooks/health checks
- **Secure cookie settings** - HttpOnly, Secure, SameSite configuration
- **Comprehensive logging** - Security event logging for monitoring

**How It Works:**
The double-submit cookie pattern works as follows:
1. Server generates a random CSRF token and sends it in a cookie
2. Server also includes the token in a response header (X-CSRF-Token) for client access
3. Client includes the token in a header or form field for state-changing requests (POST/PUT/DELETE)
4. Server validates that the cookie token matches the header/form token
5. Since attackers can't read cookies from other domains (same-origin policy), they can't include the correct token in forged requests

**Usage Examples:**

**Basic Middleware Configuration:**
```python
from unistax.middleware import MiddlewarePipeline
from unistax.csrf import CSRFProtectMiddleware

# Basic configuration
csrf = CSRFProtectMiddleware(secret="your-secret-key-here")
pipeline = MiddlewarePipeline()
pipeline.use(csrf)
```

**Production Configuration:**
```python
import os
from unistax.csrf import CSRFProtectMiddleware

csrf = CSRFProtectMiddleware(
    secret=os.environ["SECRET_KEY"],  # Use environment variable
    token_expiration=3600,  # 1 hour token lifetime
    cookie_secure=True,  # HTTPS only (production)
    cookie_samesite="strict",  # Maximum CSRF protection
    cookie_httponly=True,  # Prevent JavaScript access
    exempt_patterns=[
        r"^/api/webhook/stripe",  # Exempt webhook endpoints
        r"^/health",  # Exempt health checks
    ],
)
```

**With User Binding (Additional Security):**
```python
from unistax.csrf import CSRFProtectMiddleware

def get_user_id(request):
    """Extract user ID from request context."""
    return request.context.get("user_id")

csrf = CSRFProtectMiddleware(
    secret="your-secret-key",
    user_id_func=get_user_id,  # Bind tokens to users
    token_expiration=1800,  # 30 minutes
)
```

**Standalone Token Generation/Validation:**
```python
from unistax.csrf import CSRFProtect, CSRFTokenInvalid

# Create CSRF protect instance
csrf = CSRFProtect(secret="your-secret-key", token_expiration=3600)

# Generate token
token = csrf.generate_token()

# Validate token (double-submit pattern)
try:
    csrf.validate_token(
        cookie_token=token,  # From cookie
        header_token=token,  # From header/form
    )
    # Token valid - process request
except CSRFTokenInvalid:
    # Token invalid - reject request
    return {"error": "CSRF validation failed"}
```

**Client-Side Integration:**

For JavaScript/SPA applications:
```javascript
// 1. Get CSRF token from cookie or response header
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}

const csrfToken = getCookie('csrf_token');
// Or from response header after first request:
// const csrfToken = response.headers.get('X-CSRF-Token');

// 2. Include token in all state-changing requests
fetch('/api/update', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken  // Include CSRF token
    },
    body: JSON.stringify({ data: 'value' })
});
```

For HTML forms:
```html
<form method="POST" action="/update">
    <!-- Include CSRF token as hidden field -->
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">

    <input type="text" name="username">
    <button type="submit">Update</button>
</form>
```

**Exception Handling:**
```python
from unistax.csrf import (
    CSRFTokenMissing,
    CSRFTokenInvalid,
    CSRFTokenExpired,
)

try:
    csrf.validate_token(cookie_token, header_token)
except CSRFTokenMissing as e:
    # Token not provided in cookie or header
    return {"error": str(e), "code": "csrf_missing"}
except CSRFTokenInvalid as e:
    # Tokens don't match or signature invalid (possible attack!)
    logger.warning("CSRF attack detected: %s", e)
    return {"error": str(e), "code": "csrf_invalid"}
except CSRFTokenExpired as e:
    # Token expired - generate new token
    return {"error": str(e), "code": "csrf_expired"}
```

**Security Configuration Guide:**

| Setting | Development | Production | Notes |
|---------|-------------|------------|-------|
| `cookie_secure` | False | True | Require HTTPS for cookie |
| `cookie_samesite` | "lax" | "strict" | Prevent cross-site requests |
| `cookie_httponly` | True | True | Prevent JavaScript access |
| `token_expiration` | None | 1800-3600 | Token lifetime in seconds |
| `exempt_patterns` | [] | [webhooks] | Exempt only trusted endpoints |

**Security Best Practices:**
- ✅ Use HTTPS in production (required for cookie_secure=True)
- ✅ Set cookie_samesite="strict" for maximum protection
- ✅ Keep cookie_httponly=True to prevent XSS token theft
- ✅ Use token expiration for sensitive applications
- ✅ Only exempt trusted endpoints (webhooks, health checks)
- ✅ Use user_id_func for user-specific token binding
- ✅ Rotate secret key periodically (requires all sessions to get new tokens)
- ✅ Log CSRF validation failures for security monitoring
- ✅ Use the same secret across all server instances

**When to Exempt Endpoints:**
```python
# ✅ Good: Exempt public endpoints that don't change state
exempt_patterns=[
    r"^/api/webhook/",  # External webhooks (can't include CSRF token)
    r"^/health",        # Health check endpoints
    r"^/metrics",       # Monitoring endpoints
]

# ❌ Bad: Don't exempt state-changing endpoints
exempt_patterns=[
    r"^/api/",  # TOO BROAD - exposes all API endpoints!
    r"^/login", # LOGIN NEEDS PROTECTION!
    r"^/update", # STATE-CHANGING - NEEDS PROTECTION!
]
```

**Testing CSRF Protection:**
```python
from unistax.csrf import CSRFProtect, CSRFTokenInvalid

csrf = CSRFProtect(secret="test-secret")

# Test valid token
token = csrf.generate_token()
csrf.validate_token(token, token)  # Should succeed

# Test token mismatch (simulated attack)
token1 = csrf.generate_token()
token2 = csrf.generate_token()
try:
    csrf.validate_token(token1, token2)  # Should fail
except CSRFTokenInvalid:
    print("Attack detected and blocked!")

# Test expiration
csrf_exp = CSRFProtect(secret="test-secret", token_expiration=1)
token = csrf_exp.generate_token()
import time; time.sleep(2)
try:
    csrf_exp.validate_token(token, token)  # Should fail
except CSRFTokenExpired:
    print("Expired token rejected!")
```

**Monitoring and Logging:**

The CSRF middleware logs security events:
```python
# INFO: Middleware initialization
# "CSRFProtectMiddleware initialized: cookie=csrf_token, header=X-CSRF-Token, ..."

# DEBUG: Successful validation
# "CSRF validation successful for POST /api/update"

# WARNING: Validation failures
# "CSRF validation failed for POST /api/update: CSRF tokens don't match (possible attack!)"
```

Monitor CSRF failures for potential attacks:
- Multiple failures from same IP → Possible attack
- Sudden spike in failures → Configuration issue or attack
- Failures on sensitive endpoints → Priority investigation

---

### 6. Secrets Management Implementation (FEATURE ADDED)

**Feature:** Added comprehensive secrets management system with multiple backend support for secure secret storage and retrieval.

**Files:**
- `python/src/unistax/secrets/manager.py` - Unified SecretManager with caching and type conversion
- `python/src/unistax/secrets/adapters.py` - EnvironmentBackend and FileBackend implementations
- `python/src/unistax/secrets/base.py` - Abstract SecretBackend interface
- `python/src/unistax/secrets/exceptions.py` - Secrets-specific exceptions
- `python/src/unistax/secrets/__init__.py` - Module exports

**Security Features:**
- **Multiple backends** - Environment variables, file-based, extensible to cloud providers
- **In-memory caching** - Configurable TTL to reduce backend calls
- **Type safety** - Type conversion methods (int, bool, float, JSON, list)
- **Secret validation** - Required secrets checking on initialization
- **Fallback mechanism** - Try multiple backends in order
- **Secure file permissions** - Enforcement of 0600 or 0400 for file-based secrets
- **Never logs secrets** - Security-conscious logging throughout
- **Access audit logging** - Comprehensive logging for security monitoring

**Backends:**

1. **EnvironmentBackend** - Environment variable-based secrets:
   - Load from environment variables or .env files
   - Prefix support for namespacing
   - Case-sensitive or case-insensitive modes
   - Perfect for containerized deployments (Docker, Kubernetes)

2. **FileBackend** - File-based secrets storage:
   - JSON format for easy management
   - Secure file permissions (0600 recommended)
   - Read-only mode support
   - Automatic file creation with secure permissions
   - Warning on insecure permissions

**Usage Examples:**

**Development (Environment Variables with .env):**
```python
from unistax.secrets import SecretManager, EnvironmentBackend

# Load from .env file
backend = EnvironmentBackend.from_dotenv(".env")
manager = SecretManager(backend)

# Get secrets
database_url = manager.get("DATABASE_URL")
secret_key = manager.get("SECRET_KEY")

# Type conversion
debug_mode = manager.get_bool("DEBUG", default=False)
max_connections = manager.get_int("MAX_CONNECTIONS", default=10)
allowed_hosts = manager.get_list("ALLOWED_HOSTS")  # Comma-separated
```

**.env file** (add to .gitignore!):
```bash
# Database configuration
DATABASE_URL=postgresql://user:password@localhost/mydb
DATABASE_MAX_CONNECTIONS=20

# Application settings
SECRET_KEY=your-secret-key-here
DEBUG=false
ALLOWED_HOSTS=localhost,example.com,*.example.org

# API keys
STRIPE_API_KEY=sk_test_...
SENDGRID_API_KEY=SG...
```

**Local Deployment (File-Based):**
```python
from unistax.secrets import SecretManager, FileBackend

# Create backend with secure permissions
backend = FileBackend("secrets.json", mode=0o600)
manager = SecretManager(backend, cache_ttl=300)  # 5 minute cache

# Set secrets
manager.set("database/password", "secure-password")
manager.set("api/stripe/key", "sk_live_...")

# Get secrets
db_password = manager.get("database/password")
stripe_key = manager.get("api/stripe/key")
```

**secrets.json** (mode 0600, never commit!):
```json
{
  "database/password": "secure-password",
  "database/username": "dbuser",
  "api/stripe/key": "sk_live_...",
  "api/sendgrid/key": "SG...",
  "jwt/secret": "your-jwt-secret-key"
}
```

**Multiple Backends with Fallback:**
```python
from unistax.secrets import SecretManager, EnvironmentBackend, FileBackend

# Try environment first, then file
manager = SecretManager([
    EnvironmentBackend(),  # Check env vars first
    FileBackend("secrets.json"),  # Fallback to file
])

# Will check both backends in order
secret = manager.get("API_KEY")
```

**Production Configuration with Required Secrets:**
```python
import os
from unistax.secrets import SecretManager, EnvironmentBackend

# Environment backend with prefix
backend = EnvironmentBackend(prefix="MYAPP_")

# Validate required secrets on startup
manager = SecretManager(
    backend,
    cache_ttl=600,  # 10 minute cache
    required_secrets=[
        "DATABASE_URL",
        "SECRET_KEY",
        "JWT_SECRET",
        "STRIPE_API_KEY",
    ],
)
# Raises SecretNotFound if any are missing!

# Use in application
app.config["database_url"] = manager.get("DATABASE_URL")
app.config["secret_key"] = manager.get("SECRET_KEY")
```

**Type Conversion Examples:**
```python
from unistax.secrets import SecretManager, EnvironmentBackend

manager = SecretManager(EnvironmentBackend())

# Boolean (true/false, yes/no, 1/0, on/off)
debug = manager.get_bool("DEBUG", default=False)
maintenance_mode = manager.get_bool("MAINTENANCE_MODE", default=False)

# Integer
max_retries = manager.get_int("MAX_RETRIES", default=3)
timeout_seconds = manager.get_int("TIMEOUT_SECONDS", default=30)

# Float
rate_limit = manager.get_float("RATE_LIMIT", default=100.0)

# JSON
feature_flags = manager.get_json("FEATURE_FLAGS", default={})
# FEATURE_FLAGS='{"new_ui": true, "beta_features": false}'

# List (comma-separated)
allowed_origins = manager.get_list("CORS_ORIGINS")
# CORS_ORIGINS="http://localhost:3000,https://app.example.com"
```

**Exception Handling:**
```python
from unistax.secrets import (
    SecretManager,
    SecretNotFound,
    SecretInvalidFormat,
    SecretAccessDenied,
)

manager = SecretManager(backend)

try:
    api_key = manager.get("API_KEY")
except SecretNotFound:
    print("API_KEY not configured - using development mode")
    api_key = "dev-key"
except SecretAccessDenied:
    print("Permission denied reading secrets")
    sys.exit(1)
except SecretInvalidFormat as e:
    print(f"Invalid secret format: {e}")
    sys.exit(1)

# Type conversion errors
try:
    port = manager.get_int("PORT")
except SecretInvalidFormat:
    print("PORT must be a valid integer")
    port = 8000
```

**Advanced Usage - Secret Listing:**
```python
manager = SecretManager(FileBackend("secrets.json"))

# List all secrets (keys only, not values!)
all_secrets = manager.list()

# List with prefix
database_secrets = manager.list("database/")
api_keys = manager.list("api/")

# Check if secret exists
if manager.exists("OPTIONAL_FEATURE_KEY"):
    feature_key = manager.get("OPTIONAL_FEATURE_KEY")
```

**Security Best Practices:**

| Environment | Backend | Configuration | Security Notes |
|-------------|---------|---------------|----------------|
| Development | EnvironmentBackend | .env file | Add .env to .gitignore |
| Testing | FileBackend | secrets.test.json | Use test-specific secrets |
| Staging | EnvironmentBackend | Container env vars | Use staging secrets |
| Production | Cloud provider | AWS/GCP/Azure | Use IAM roles, rotate regularly |
| Local deploy | FileBackend | mode=0600 | Restrict file permissions |

**File Permissions:**
```python
# Production - read-only
backend = FileBackend("secrets.json", mode=0o400, readonly=True)

# Development - read-write
backend = FileBackend("secrets.json", mode=0o600)

# Shared server - user-only access
backend = FileBackend("secrets.json", mode=0o600)
# File permissions: -rw------- (owner only)
```

**Caching Strategy:**
```python
# No caching (always fetch from backend)
manager = SecretManager(backend, cache_ttl=None)

# Short cache for frequently accessed secrets
manager = SecretManager(backend, cache_ttl=60)  # 1 minute

# Long cache for rarely changing secrets
manager = SecretManager(backend, cache_ttl=3600)  # 1 hour

# Clear cache when secrets updated
manager.clear_cache()
```

**Best Practices:**

1. **Never commit secrets to version control:**
   ```bash
   # .gitignore
   .env
   .env.*
   secrets.json
   secrets-*.json
   *.secret
   ```

2. **Use different secrets per environment:**
   ```python
   # Development
   manager = SecretManager(EnvironmentBackend.from_dotenv(".env.development"))

   # Production
   manager = SecretManager(EnvironmentBackend.from_dotenv(".env.production"))
   ```

3. **Validate required secrets on startup:**
   ```python
   manager = SecretManager(
       backend,
       required_secrets=["DATABASE_URL", "SECRET_KEY", "API_KEY"],
   )
   # Application won't start without these secrets
   ```

4. **Use type conversion for type safety:**
   ```python
   # Don't
   port = int(manager.get("PORT"))  # May raise ValueError

   # Do
   port = manager.get_int("PORT", default=8000)  # Type-safe with default
   ```

5. **Use secure file permissions:**
   ```bash
   # Set secure permissions
   chmod 600 secrets.json

   # Verify permissions
   ls -la secrets.json
   # -rw------- 1 user user ... secrets.json
   ```

6. **Rotate secrets regularly:**
   ```python
   # Update secret
   manager.set("API_KEY", "new-key-value")

   # Clear cache to ensure new value is used
   manager.clear_cache()
   ```

7. **Monitor secret access:**
   ```python
   # Enable logging
   import logging
   logging.basicConfig(level=logging.INFO)

   # Logs will include:
   # - Secret retrievals (key name, backend used)
   # - Cache hits/misses
   # - Missing secrets
   # - Permission errors
   ```

**Security Considerations:**

- ✅ Environment variables may be visible in process listings (ps, /proc)
- ✅ File-based secrets need proper permissions (0600 or 0400)
- ✅ Never log secret values (only log keys for audit)
- ✅ Use HTTPS for cloud secret managers (future)
- ✅ Implement secret rotation policies
- ✅ Use separate secrets for different environments
- ✅ Monitor secret access for suspicious activity
- ✅ Use caching wisely (balance performance vs. freshness)
- ✅ Validate secret format before using
- ✅ Use required_secrets for critical configuration

---

## Remaining Security Concerns

### HIGH PRIORITY (Requires Immediate Action)

#### 1. Custom JWT Implementation ✅ FIXED

**Status:** IMPLEMENTED - Using industry-standard PyJWT library.

**File:** `python/src/unistax/security/jwt.py`

The JWT implementation has been completely rewritten to use PyJWT, addressing all security concerns:

**Security Improvements:**
- ✅ Industry-standard PyJWT library (battle-tested, actively maintained)
- ✅ Support for multiple algorithms (HS256/384/512, RS256/384/512, ES256/384/512)
- ✅ Algorithm verification (prevents algorithm confusion attacks)
- ✅ Expiration (exp) claim validation
- ✅ Not-before (nbf) claim validation
- ✅ Issued-at (iat) claim validation
- ✅ Audience (aud) claim validation
- ✅ Issuer (iss) claim validation
- ✅ Proper error handling with specific exception types
- ✅ Secret strength validation (warns if too weak)
- ✅ Clock skew handling (configurable leeway)
- ✅ Comprehensive logging for security events

**New Exception Types:**
- `JWTError` - Base exception
- `JWTDecodeError` - Invalid token format
- `JWTExpiredError` - Token expired
- `JWTInvalidSignatureError` - Signature verification failed
- `JWTInvalidAudienceError` - Audience validation failed
- `JWTInvalidIssuerError` - Issuer validation failed

**Usage:**
```python
from unistax.security import JWT, JWTExpiredError, JWTInvalidSignatureError

# Basic usage with HS256
jwt_manager = JWT(
    secret="your-strong-256-bit-secret-key-here",
    algorithm="HS256",
    expiration=3600  # 1 hour
)

# Encode token
token = jwt_manager.encode({"user_id": 123, "role": "admin"})

# Decode and verify token
try:
    claims = jwt_manager.decode(token)
    user_id = claims["user_id"]
except JWTExpiredError:
    # Handle expired token - require re-authentication
    pass
except JWTInvalidSignatureError:
    # Handle forged token - log security incident!
    pass

# With audience and issuer validation (recommended)
jwt_manager = JWT(
    secret="your-secret",
    algorithm="HS256",
    audience="myapp",
    issuer="auth-service",
    expiration=1800  # 30 minutes
)
token = jwt_manager.encode({"user_id": 123})
claims = jwt_manager.decode(token)  # Validates aud and iss

# Using RS256 with public/private keys (recommended for distributed systems)
with open("private_key.pem") as f:
    private_key = f.read()
with open("public_key.pem") as f:
    public_key = f.read()

jwt_manager = JWT(
    secret=private_key,
    public_key=public_key,
    algorithm="RS256"
)
token = jwt_manager.encode({"user_id": 123})
claims = jwt_manager.decode(token)
```

**Security Best Practices:**
- Use secrets of at least 256 bits (32 characters) for HS256
- Use RS256 or ES256 for public/private key scenarios
- Set expiration times as short as practical (15-60 minutes)
- Always validate audience and issuer in production
- Never disable signature verification
- Implement token refresh mechanism for long-lived sessions
- Consider token revocation for sensitive operations (use Redis/database)

See documentation in `python/src/unistax/security/jwt.py` for more details.

#### 2. Authorization Bypass ✅ FIXED

**Status:** FIXED - See "Recent Security Fixes" section above.

RBAC authorization is now properly enforced. See commit "security: implement RBAC, fix CORS, and improve error handling" for details.

#### 3. Insecure CORS Configuration ✅ FIXED

**Status:** FIXED - See "Recent Security Fixes" section above.

CORS now requires explicit origin configuration. See commit "security: implement RBAC, fix CORS, and improve error handling" for details.

#### 4. No Rate Limiting on Auth Endpoints ✅ FIXED

**Status:** IMPLEMENTED - See "Recent Security Fixes" section #4 above.

Comprehensive rate limiting has been implemented with:
- RateLimitMiddleware for HTTP requests
- Per-IP, per-user, and per-endpoint rate limiting
- Standard rate limit headers (X-RateLimit-*)
- Redis support for distributed systems
- Comprehensive logging and monitoring

Usage:
```python
from unistax.ratelimit import RateLimiter, RateLimitMiddleware

# Protect authentication endpoints: 5 attempts per 5 minutes
auth_limiter = RateLimiter(limit=5, window=300)

@app.post("/login")
@auth_limiter.limit(key_func=lambda username: f"login:{username}")
async def login(username: str, password: str):
    # Login logic
    pass
```

See documentation above for complete usage examples and recommended limits.

---

### MEDIUM PRIORITY

#### 1. No CSRF Protection ✅ FIXED

**Status:** IMPLEMENTED - See "Recent Security Fixes" section #5 above.

Comprehensive CSRF protection has been implemented with:
- CSRFProtectMiddleware for HTTP requests
- Double-submit cookie pattern (stateless)
- Cryptographically secure token generation
- HMAC signature validation
- Token expiration support
- User-specific token binding (optional)
- Exempt endpoint patterns
- Comprehensive logging and monitoring

Usage:
```python
from unistax.csrf import CSRFProtectMiddleware

csrf = CSRFProtectMiddleware(
    secret="your-secret-key",
    token_expiration=3600,  # 1 hour
    cookie_secure=True,  # HTTPS only
    cookie_samesite="strict",  # Maximum protection
)
```

See documentation above for complete usage examples and configuration options.

#### 2. Missing Security Headers ✅ FIXED

**Status:** IMPLEMENTED - See "Recent Security Fixes" section #3 above.

The SecurityHeadersMiddleware is now available with comprehensive OWASP-recommended headers:
- Content-Security-Policy (CSP)
- Strict-Transport-Security (HSTS)
- X-Frame-Options
- X-Content-Type-Options
- Referrer-Policy
- Permissions-Policy
- X-XSS-Protection

Usage:
```python
from unistax.middleware import SecurityHeadersMiddleware

security = SecurityHeadersMiddleware()  # Uses secure defaults
# Add to your middleware pipeline
```

See documentation above for complete usage examples and configuration options.

#### 3. Secrets Management ✅ FIXED

**Status:** IMPLEMENTED - See "Recent Security Fixes" section #6 above.

Comprehensive secrets management has been implemented with:
- SecretManager with multiple backend support
- EnvironmentBackend for environment variables and .env files
- FileBackend for JSON-based secrets with secure permissions
- In-memory caching with configurable TTL
- Type conversion (string, int, bool, float, JSON, list)
- Required secrets validation
- Fallback mechanism across multiple backends
- Comprehensive logging and audit trails

Usage:
```python
from unistax.secrets import SecretManager, EnvironmentBackend

# Load from .env file
backend = EnvironmentBackend.from_dotenv(".env")
manager = SecretManager(backend)

# Get secrets with type safety
database_url = manager.get("DATABASE_URL")
debug_mode = manager.get_bool("DEBUG", default=False)
max_connections = manager.get_int("MAX_CONNECTIONS", default=10)
```

See documentation above for complete usage examples, file-based backend, and configuration options.

---

## Security Best Practices

### 1. Input Validation

Always validate user input:
```python
from unistax.validation.validators import Validator

validator = Validator()
validator.add_rule("email", "email")
validator.add_rule("age", "min", 18)
validator.add_rule("age", "max", 120)

if not validator.validate(user_data):
    raise ValueError(validator.errors)
```

### 2. Parameterized Queries

Never concatenate SQL:
```python
# BAD
query = f"SELECT * FROM users WHERE id = {user_id}"

# GOOD
query = "SELECT * FROM users WHERE id = :id"
result = session.execute(text(query), {"id": user_id})
```

### 3. Error Handling

Don't leak sensitive information in errors:
```python
# BAD
except Exception as e:
    return {"error": str(e)}  # Leaks stack trace!

# GOOD
except Exception as e:
    logger.error(f"Database error: {e}", exc_info=True)
    return {"error": "An error occurred. Please try again."}
```

### 4. Authentication Best Practices

```python
# Use secure session management
from unistax.security.sessions import SecureSessionManager

session_manager = SecureSessionManager(
    secret_key=os.environ["SESSION_SECRET"],
    secure=True,  # HTTPS only
    httponly=True,  # No JavaScript access
    samesite="strict"  # CSRF protection
)
```

### 5. Audit Logging

Log security events:
```python
from unistax.audit.logger import AuditLogger

audit = AuditLogger()

# Log authentication events
audit.log_event("user.login", user_id=user.id, ip=request.client.host)
audit.log_event("user.login.failed", username=username, ip=request.client.host)

# Log data access
audit.log_event("data.access", resource="user", action="read", user_id=user.id)
```

---

## Security Checklist for Production

- [ ] Enable bcrypt for password hashing (`pip install bcrypt`)
- [ ] Replace custom JWT with PyJWT library
- [ ] Implement RBAC decorator properly
- [ ] Configure CORS with specific origins
- [ ] Add rate limiting to authentication endpoints
- [ ] Enable CSRF protection
- [ ] Add security headers
- [ ] Move secrets to environment variables or secrets manager
- [ ] Enable HTTPS/TLS
- [ ] Set up audit logging
- [ ] Configure session security (httponly, secure, samesite)
- [ ] Implement input validation on all endpoints
- [ ] Use parameterized queries everywhere
- [ ] Set up monitoring and alerting for security events
- [ ] Regular dependency updates (`pip-audit`)
- [ ] Penetration testing
- [ ] Code review for security issues

---

## Incident Response

If you discover a security vulnerability:

1. **Don't** disclose publicly until patched
2. Email security concerns to: [security contact]
3. Include:
   - Description of vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

---

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [Python Security Best Practices](https://python.readthedocs.io/en/latest/library/security_warnings.html)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)

---

## Testing

Comprehensive test suites have been implemented for all security features to ensure reliability and prevent regressions.

### Test Coverage

**Test Files:**
- `tests/security/test_jwt.py` - JWT implementation tests (25+ tests)
- `tests/security/test_csrf.py` - CSRF protection tests (20+ tests)
- `tests/security/test_ratelimit.py` - Rate limiting tests (15+ tests)
- `tests/security/test_secrets.py` - Secrets management tests (30+ tests)

**Total:** 90+ comprehensive security tests

### Running Tests

**Install test dependencies:**
```bash
pip install -r requirements-dev.txt
```

**Run all tests:**
```bash
pytest
```

**Run specific test file:**
```bash
pytest tests/security/test_jwt.py
pytest tests/security/test_csrf.py
pytest tests/security/test_ratelimit.py
pytest tests/security/test_secrets.py
```

**Run tests by marker:**
```bash
pytest -m jwt          # Run JWT tests only
pytest -m csrf         # Run CSRF tests only
pytest -m ratelimit    # Run rate limiting tests only
pytest -m secrets      # Run secrets management tests only
pytest -m unit         # Run unit tests only
pytest -m integration  # Run integration tests only
```

**Run with coverage:**
```bash
pytest --cov=src/unistax --cov-report=html --cov-report=term-missing
```

**Run in parallel (faster):**
```bash
pytest -n auto  # Requires pytest-xdist
```

### Test Categories

**JWT Tests** (`test_jwt.py`):
- ✅ Basic token generation and validation
- ✅ Token expiration and not-before claims
- ✅ Invalid signature detection
- ✅ Audience and issuer validation
- ✅ Multiple algorithm support (HS256, HS384, HS512)
- ✅ Custom claims handling
- ✅ Clock skew handling with leeway
- ✅ Weak secret warnings

**CSRF Tests** (`test_csrf.py`):
- ✅ Token generation and validation
- ✅ Double-submit pattern verification
- ✅ Token mismatch detection
- ✅ Token expiration
- ✅ User-specific token binding
- ✅ Invalid signature detection
- ✅ Token format validation
- ✅ Multiple tokens with same secret

**Rate Limiting Tests** (`test_ratelimit.py`):
- ✅ Basic rate limiting enforcement
- ✅ Rate limit info tracking
- ✅ Independent keys
- ✅ Window reset after expiration
- ✅ Manual reset functionality
- ✅ Clear all limits
- ✅ Multi-token consumption
- ✅ Concurrent requests simulation
- ✅ In-memory storage backend

**Secrets Management Tests** (`test_secrets.py`):
- ✅ Environment backend (get, set, delete, list)
- ✅ File backend with secure permissions
- ✅ .env file loading
- ✅ Type conversion (int, bool, float, JSON, list)
- ✅ Caching with TTL
- ✅ Multiple backend fallback
- ✅ Required secrets validation
- ✅ Read-only mode
- ✅ Insecure permissions warnings
- ✅ Invalid JSON handling

### Test Best Practices

1. **Run tests before committing:**
   ```bash
   pytest tests/security/
   ```

2. **Ensure all tests pass:**
   ```bash
   pytest --tb=short -v
   ```

3. **Check test coverage:**
   ```bash
   pytest --cov=src/unistax/security --cov-report=term-missing
   ```

4. **Run linting before tests:**
   ```bash
   ruff check src/ tests/
   black --check src/ tests/
   ```

### Continuous Integration

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: pip install -r requirements-dev.txt
      - run: ruff check src/ tests/
      - run: black --check src/ tests/
      - run: pytest --cov=src/unistax --cov-report=xml
      - uses: codecov/codecov-action@v3
```

### Adding New Tests

When implementing new security features:

1. **Create test file** in `tests/security/test_feature.py`
2. **Add test markers** (`@pytest.mark.unit`, `@pytest.mark.feature`)
3. **Write comprehensive tests** covering:
   - Normal operation
   - Edge cases
   - Error conditions
   - Security scenarios
4. **Run tests** to ensure they pass
5. **Update this documentation** with new test info

**Example test structure:**
```python
import pytest
from unistax.security import MyFeature

@pytest.mark.unit
@pytest.mark.myfeature
class TestMyFeature:
    """Test my security feature."""

    def test_basic_functionality(self):
        """Test basic feature operation."""
        feature = MyFeature(config="value")
        result = feature.process("input")
        assert result == "expected"

    def test_error_handling(self):
        """Test error conditions."""
        feature = MyFeature(config="value")
        with pytest.raises(ValueError):
            feature.process("invalid")

    def test_security_scenario(self):
        """Test security-specific scenario."""
        feature = MyFeature(config="value")
        # Test attack scenario
        assert feature.is_secure() is True
```

---

## Changelog

### 2024-11-13
- ✅ Migrated password hashing from SHA256 to bcrypt
- ✅ Added comprehensive SQL injection prevention
- ✅ Added input validation to query builder
- ✅ Implemented RBAC authorization (fixed bypass vulnerability)
- ✅ Added security context management (thread-safe user context)
- ✅ Fixed CORS configuration security (removed wildcard default)
- ✅ Improved error handling with proper logging
- ✅ Implemented SecurityHeadersMiddleware with OWASP headers
- ✅ Added CSP, HSTS, X-Frame-Options, and other security headers
- ✅ Replaced custom JWT with industry-standard PyJWT library
- ✅ Implemented comprehensive rate limiting middleware
- ✅ Added RateLimitMiddleware for HTTP request protection
- ✅ Added InMemoryStorage and RedisStorage backends
- ✅ Standard rate limit headers (X-RateLimit-Limit/Remaining/Reset)
- ✅ Protection against brute force attacks on authentication endpoints
- ✅ Added comprehensive JWT claim validation (exp, nbf, iat, aud, iss)
- ✅ Added algorithm verification (prevents algorithm confusion attacks)
- ✅ Added support for RS256, ES256, and other secure algorithms
- ✅ Added specific JWT exception types for better error handling
- ✅ Implemented CSRF protection middleware
- ✅ Added CSRFProtectMiddleware using double-submit cookie pattern
- ✅ Cryptographically secure token generation with HMAC validation
- ✅ Support for token expiration and user-specific binding
- ✅ Configurable exempt endpoints and secure cookie settings
- ✅ Protection against Cross-Site Request Forgery attacks
- ✅ Implemented comprehensive secrets management system
- ✅ Added SecretManager with multiple backend support
- ✅ Added EnvironmentBackend for environment variables and .env files
- ✅ Added FileBackend for JSON-based secrets with secure permissions
- ✅ Type conversion methods (string, int, bool, float, JSON, list)
- ✅ Required secrets validation on startup
- ✅ In-memory caching with configurable TTL
- ✅ Fallback mechanism across multiple backends
- ✅ Secure file permissions enforcement (0600/0400)
- ✅ Implemented comprehensive security test suite
- ✅ Added 90+ unit and integration tests for all security features
- ✅ JWT tests (25+ tests): token generation, validation, expiration, claims
- ✅ CSRF tests (20+ tests): double-submit pattern, token validation, expiration
- ✅ Rate limiting tests (15+ tests): enforcement, window reset, storage backends
- ✅ Secrets management tests (30+ tests): backends, type conversion, caching
- ✅ Added pytest configuration and test markers
- ✅ Added requirements-dev.txt for test dependencies
- ✅ Documented testing best practices and CI integration
- ✅ Added secret strength validation
- ✅ Documented remaining security concerns
- ✅ Created security best practices guide
