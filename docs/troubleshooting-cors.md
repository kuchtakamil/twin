# Troubleshooting CORS Issues - Case Study

## Problem
Aplikacja działająca za reverse proxy (Caddy) na `https://twin.kamilkuchta.pl`
nie mogła wykonać requestów do API Gateway z powodu błędu CORS:
```
Cross-Origin Request Blocked: The Same Origin Policy disallows reading the remote resource.
(Reason: CORS header 'Access-Control-Allow-Origin' missing). Status code: 204
```

## Architektura
```
Browser → twin.kamilkuchta.pl (Caddy) → CloudFront (dkhf49puf9j9v.cloudfront.net)
                                              ↓
                                         API Gateway → Lambda
```

## Diagnostyka

### 1. Sprawdzenie zmiennych środowiskowych Lambda
```bash
aws lambda get-function-configuration \
  --function-name twin-dev-api \
  --query 'Environment.Variables'
```
**Output:** Pokazuje że `CORS_ORIGINS` zawiera tylko CloudFront domain

### 2. Sprawdzenie konfiguracji CORS w API Gateway
```bash
aws apigatewayv2 get-apis \
  --query 'Items[?Name==`twin-dev-api-gateway`].{Name:Name,ApiEndpoint:ApiEndpoint,CorsConfig:CorsConfiguration}' \
  | jq '.[0]'
```
**Output:** Pokazuje AllowOrigins zawiera tylko `https://dkhf49puf9j9v.cloudfront.net`

### 3. Sprawdzenie zdefiniowanych tras w API Gateway
```bash
aws apigatewayv2 get-routes \
  --api-id iddqg55ifb \
  --query 'Items[].{RouteKey:RouteKey,Target:Target}'
```
**Output:** Pokazuje że są trasy GET i POST, ale API Gateway v2 automatycznie obsługuje OPTIONS

### 4. Test preflight request (OPTIONS) z poprawnym Origin
```bash
curl -i -X OPTIONS https://iddqg55ifb.execute-api.eu-central-1.amazonaws.com/chat \
  -H "Origin: https://dkhf49puf9j9v.cloudfront.net" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```
**Output:** HTTP 204 z poprawnymi headerami CORS - więc CORS działa dla CloudFront domain

### 5. Test z domain które NIE jest w allowed origins
```bash
curl -i -X OPTIONS https://iddqg55ifb.execute-api.eu-central-1.amazonaws.com/chat \
  -H "Origin: https://twin.kamilkuchta.pl" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```
**Output:** Brak `access-control-allow-origin` header lub origin odrzucony

## Przyczyna
Browser widzi origin jako `https://twin.kamilkuchta.pl` (domain VPS),
ale API Gateway akceptuje tylko `https://dkhf49puf9j9v.cloudfront.net`.

## Rozwiązanie

### 1. Edycja Terraform configuration
Plik: `terraform/main.tf`

```terraform
# PRZED:
cors_origins = var.use_custom_domain ? [
  "https://${var.root_domain}",
  "https://www.${var.root_domain}"
] : ["https://${aws_cloudfront_distribution.main.domain_name}"]

# PO:
cors_origins = var.use_custom_domain ? [
  "https://${var.root_domain}",
  "https://www.${var.root_domain}"
] : [
  "https://${aws_cloudfront_distribution.main.domain_name}",
  "https://twin.kamilkuchta.pl"  # VPS reverse proxy domain
]
```

### 2. Inicjalizacja Terraform backend
```bash
cd /home/kamil/repos/twin/terraform

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=eu-central-1

echo "yes" | terraform init \
  -backend-config="bucket=twin-terraform-state-${AWS_ACCOUNT_ID}" \
  -backend-config="key=dev/terraform.tfstate" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="dynamodb_table=twin-terraform-locks" \
  -backend-config="encrypt=true"
```

### 3. Wybór workspace
```bash
terraform workspace select dev
```

### 4. Apply zmian
```bash
terraform apply \
  -var="project_name=twin" \
  -var="environment=dev" \
  -auto-approve
```

**Terraform zaktualizuje:**
- API Gateway CORS configuration (`AllowOrigins`)
- Lambda environment variables (`CORS_ORIGINS`)
- CloudFront viewer certificate settings

### 5. Weryfikacja zmian
```bash
# Sprawdź updated CORS config
aws apigatewayv2 get-apis \
  --query 'Items[?Name==`twin-dev-api-gateway`].CorsConfiguration' \
  | jq '.[0].AllowOrigins'

# Test OPTIONS request z nowym origin
curl -i -X OPTIONS https://iddqg55ifb.execute-api.eu-central-1.amazonaws.com/chat \
  -H "Origin: https://twin.kamilkuchta.pl" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```

**Output:**
- AllowOrigins zawiera oba domains
- OPTIONS request zwraca `access-control-allow-origin: https://twin.kamilkuchta.pl`

## Kluczowe wnioski

1. **API Gateway v2** automatycznie obsługuje OPTIONS requests gdy CORS jest skonfigurowany
2. **Origin header** w browser request musi **dokładnie pasować** do jednego z `AllowOrigins`
3. **Reverse proxy** zmienia origin z perspektywy browsera (browser nie widzi CloudFront, tylko VPS domain)
4. **Terraform apply** natychmiast aktualizuje infrastrukturę - nie trzeba czekać na deployment
5. **CORS configuration** jest w dwóch miejscach:
   - API Gateway (`cors_configuration` block)
   - Lambda environment variables (używane przez FastAPI middleware)

## Przydatne komendy AWS CLI

```bash
# Lista wszystkich API Gateway
aws apigatewayv2 get-apis --query 'Items[].{Name:Name,Id:ApiId,Endpoint:ApiEndpoint}'

# Lista wszystkich Lambda functions
aws lambda list-functions --query 'Functions[].{Name:FunctionName,Runtime:Runtime}'

# Logi Lambda (wymaga log group name)
aws logs tail /aws/lambda/twin-dev-api --follow

# CloudFront distributions
aws cloudfront list-distributions --query 'DistributionList.Items[].{Id:Id,DomainName:DomainName,Status:Status}'

# Sprawdzenie Terraform workspace
terraform workspace list
terraform workspace show

# Terraform outputs
terraform output
terraform output -json
```

## Alternatywne rozwiązania

### Opcja 1: Wildcard subdomain (NIE ZALECANE w produkcji)
```terraform
cors_origins = ["https://*.kamilkuchta.pl"]
```
⚠️ Może być zbyt permisywne dla security

### Opcja 2: Dodać wszystkie expected domains do zmiennej
```terraform
variable "additional_cors_origins" {
  type    = list(string)
  default = []
}

cors_origins = concat(
  ["https://${aws_cloudfront_distribution.main.domain_name}"],
  var.additional_cors_origins
)
```

### Opcja 3: Proxy przez Caddy (bez direct API calls)
Zamiast frontend → API Gateway, zrobić:
frontend → Caddy → API Gateway

Wtedy Caddy może dodawać odpowiednie headers i origin nie jest problem.
