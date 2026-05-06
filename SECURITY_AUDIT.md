# Security Audit Report

**Project:** AI Digital Twin
**Date:** 2026-01-22
**Auditor:** Claude Code (Automated Security Review)

---

## Executive Summary

This security audit identified **16 vulnerabilities** across the application stack:
- **3 Critical/High** severity issues
- **7 Medium** severity issues
- **6 Low** severity issues

The most critical finding is a **Path Traversal vulnerability** in the session management system that could allow attackers to read or write arbitrary files on the server.

---

## Critical/High Severity

### 1. Path Traversal in Session Management (CRITICAL)

**Location:** `backend/server.py:71-90`

**Description:** The `session_id` parameter is used directly to construct file paths without any validation. An attacker can craft malicious session IDs to read or write files outside the intended `memory/` directory.

**Vulnerable Code:**
```python
def get_memory_path(session_id: str) -> str:
    return f"{session_id}.json"  # No validation!

def load_conversation(session_id: str) -> List[Dict]:
    file_path = os.path.join(MEMORY_DIR, get_memory_path(session_id))
    # Attacker can use session_id like "../../etc/passwd"
```

**Attack Vector:**
```bash
curl -X POST http://api/chat \
  -d '{"message": "hello", "session_id": "../../etc/passwd"}'
```

**Impact:** Arbitrary file read/write on Lambda filesystem (limited impact due to Lambda's ephemeral nature, but critical in local development mode).

**Recommendation:**
```python
import re

def validate_session_id(session_id: str) -> bool:
    return bool(re.match(r'^[a-f0-9\-]{36}$', session_id))  # UUID format only

def get_memory_path(session_id: str) -> str:
    if not validate_session_id(session_id):
        raise ValueError("Invalid session ID format")
    return f"{session_id}.json"
```

---

### 2. Overly Permissive IAM Policies (HIGH)

**Location:** `terraform/main.tf:112-120`

**Description:** Lambda function uses AWS managed policies with excessive permissions:

```hcl
resource "aws_iam_role_policy_attachment" "lambda_bedrock" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"  # Too broad
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"  # Access to ALL S3 buckets!
}
```

**Impact:** If Lambda is compromised, attacker gains access to ALL S3 buckets in the account and full Bedrock control.

**Recommendation:** Use least-privilege inline policies:
```hcl
resource "aws_iam_role_policy" "lambda_s3" {
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = "${aws_s3_bucket.memory.arn}/*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_bedrock" {
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:aws:bedrock:*::foundation-model/amazon.nova-*"
    }]
  })
}
```

---

### 3. No Input Size Limits (HIGH)

**Location:** `backend/server.py:54-56`

**Description:** The `ChatRequest` model accepts messages of unlimited length:

```python
class ChatRequest(BaseModel):
    message: str  # No max_length constraint
    session_id: Optional[str] = None
```

**Impact:**
- Denial of Service through memory exhaustion
- Excessive Bedrock API costs (tokens are expensive)
- Potential for prompt injection attacks with large payloads

**Recommendation:**
```python
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(None, pattern=r'^[a-f0-9\-]{36}$')
```

---

## Medium Severity

### 4. Overly Permissive CORS in API Gateway

**Location:** `terraform/main.tf:153-159`

**Description:**
```hcl
cors_configuration {
  allow_origins = ["*"]  # Allows any website to call the API
}
```

**Impact:** Any website can make requests to the API, enabling CSRF-like attacks and unauthorized usage.

**Recommendation:** Restrict to CloudFront domain:
```hcl
cors_configuration {
  allow_origins = var.use_custom_domain ? [
    "https://${var.root_domain}",
    "https://www.${var.root_domain}"
  ] : ["https://${aws_cloudfront_distribution.main.domain_name}"]
}
```

---

### 5. Information Disclosure in Endpoints

**Location:** `backend/server.py:165-181`

**Description:** Root and health endpoints expose internal configuration:

```python
@app.get("/")
async def root():
    return {
        "message": "AI Digital Twin API (Powered by AWS Bedrock)",
        "memory_enabled": True,
        "storage": "S3" if USE_S3 else "local",
        "ai_model": BEDROCK_MODEL_ID  # Exposes model info
    }
```

**Impact:** Attackers learn about infrastructure stack, storage mechanisms, and AI models used.

**Recommendation:** Remove sensitive information from public endpoints:
```python
@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

---

### 6. No Authentication/Authorization

**Location:** All API endpoints

**Description:** The API is completely public. Anyone can:
- Send unlimited chat messages
- Access any conversation by guessing session IDs
- Consume AWS Bedrock resources (cost attack)

**Impact:**
- Financial abuse through API cost accumulation
- Access to other users' conversations
- Resource exhaustion

**Recommendation:** Implement at minimum:
- API key authentication
- Rate limiting per IP/session
- Consider Cognito for user authentication

---

### 7. S3 Memory Bucket Missing Encryption

**Location:** `terraform/main.tf:19-23`

**Description:** The S3 bucket storing conversation history has no server-side encryption configured.

**Impact:** Conversation data stored in plaintext at rest.

**Recommendation:**
```hcl
resource "aws_s3_bucket_server_side_encryption_configuration" "memory" {
  bucket = aws_s3_bucket.memory.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
```

---

### 8. Public S3 Frontend Bucket

**Location:** `terraform/main.tf:48-86`

**Description:** Frontend bucket is publicly accessible instead of using CloudFront Origin Access Identity (OAI).

**Impact:**
- Direct S3 URL exposure
- Bypasses CloudFront security features
- No access logging at bucket level

**Recommendation:** Use CloudFront OAI:
```hcl
resource "aws_cloudfront_origin_access_identity" "frontend" {
  comment = "OAI for frontend bucket"
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_cloudfront_origin_access_identity.frontend.iam_arn }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
    }]
  })
}
```

---

### 9. Error Messages Expose Internal Details

**Location:** `backend/server.py:151-162, 215-217`

**Description:**
```python
raise HTTPException(status_code=500, detail=f"Bedrock error: {str(e)}")
# ...
raise HTTPException(status_code=500, detail=str(e))
```

**Impact:** Exception messages may reveal internal paths, AWS configurations, or stack traces.

**Recommendation:** Log detailed errors, return generic messages:
```python
import logging
logger = logging.getLogger(__name__)

except Exception as e:
    logger.error(f"Chat error: {str(e)}", exc_info=True)
    raise HTTPException(status_code=500, detail="An internal error occurred")
```

---

### 10. Potential Prompt Injection

**Location:** `backend/context.py`

**Description:** While the system prompt includes jailbreak warnings, there's no technical validation of user input for prompt injection patterns.

**Impact:** Users may attempt to override system instructions.

**Recommendation:**
- Implement input sanitization
- Use structured outputs where possible
- Monitor for suspicious patterns
- Consider content filtering API

---

## Low Severity

### 11. Debug Output in Lambda Handler

**Location:** `backend/lambda_handler.py:5-7`

**Description:**
```python
print(f"PYTHONPATH: {sys.path}")
print(f"CWD: {os.getcwd()}")
print(f"Directory listing: {os.listdir(os.getcwd())}")
```

**Impact:** Logs contain environment details useful for reconnaissance.

**Recommendation:** Remove debug prints or guard with environment check:
```python
if os.getenv("DEBUG") == "true":
    print(f"PYTHONPATH: {sys.path}")
```

---

### 12. Missing Content Security Policy

**Location:** Frontend (Next.js)

**Description:** No CSP headers are configured to prevent XSS attacks.

**Recommendation:** Add CSP headers in `next.config.ts`:
```typescript
const securityHeaders = [
  {
    key: 'Content-Security-Policy',
    value: "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';"
  }
];
```

---

### 13. Unused OpenAI Dependency

**Location:** `backend/pyproject.toml:9`

**Description:**
```toml
"openai>=2.14.0",  # Not used in codebase
```

**Impact:** Increases attack surface unnecessarily. Each dependency is a potential vulnerability vector.

**Recommendation:** Remove unused dependency.

---

### 14. HTTP Connection Between CloudFront and S3

**Location:** `terraform/main.tf:226-227`

**Description:**
```hcl
origin_protocol_policy = "http-only"
```

**Impact:** Data transmitted unencrypted between CloudFront and S3.

**Recommendation:** Use S3 bucket domain with OAI instead of website endpoint to enable HTTPS.

---

### 15. No Input Sanitization in Frontend

**Location:** `frontend/components/twin.tsx`

**Description:** User input is sent directly to API without sanitization.

**Impact:** While React handles XSS protection for rendering, the raw input could cause issues if logged or processed elsewhere.

**Recommendation:** Add basic input sanitization before API calls.

---

### 16. Conversation Endpoint Allows Enumeration

**Location:** `backend/server.py:220-227`

**Description:**
```python
@app.get("/conversation/{session_id}")
async def get_conversation(session_id: str):
    conversation = load_conversation(session_id)
    return {"session_id": session_id, "messages": conversation}
```

**Impact:** Attackers can enumerate session IDs to access other users' conversations.

**Recommendation:**
- Require authentication
- Use unpredictable session IDs (already UUIDs, but validation needed)
- Consider removing this endpoint if not needed

---

## Dependency Check

### Python Dependencies
| Package | Version | Status |
|---------|---------|--------|
| boto3 | >=1.42.21 | OK |
| fastapi | >=0.128.0 | OK |
| mangum | >=0.20.0 | OK |
| openai | >=2.14.0 | Unused - remove |
| pypdf | >=6.5.0 | OK |
| python-dotenv | >=1.2.1 | OK |
| uvicorn | >=0.40.0 | OK |

### JavaScript Dependencies
| Package | Version | Status |
|---------|---------|--------|
| next | 16.1.1 | OK |
| react | 19.2.3 | OK |
| lucide-react | ^0.562.0 | OK |

**Recommendation:** Run regular vulnerability scans:
```bash
# Python
pip-audit

# JavaScript
npm audit
```

---

## Summary of Recommendations

### Immediate Actions (Critical/High)
1. Fix Path Traversal - validate session_id format
2. Implement least-privilege IAM policies
3. Add input size limits to API

### Short-term Actions (Medium)
4. Restrict CORS to specific origins
5. Remove information disclosure from endpoints
6. Enable S3 encryption
7. Implement CloudFront OAI for frontend bucket
8. Sanitize error messages

### Long-term Actions (Low + Architecture)
9. Add authentication layer (API keys or Cognito)
10. Implement proper rate limiting
11. Add Content Security Policy
12. Remove unused dependencies
13. Set up security monitoring and alerting
14. Consider WAF for API Gateway

---

## Files Modified During Audit

None - this is a read-only security assessment.

---

*This report was generated automatically. Manual review and penetration testing are recommended before production deployment.*