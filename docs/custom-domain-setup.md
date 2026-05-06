# Konfiguracja Custom Domain dla Twin

## Problem

Link CloudFront zmienia się przy każdym redeploy, co utrudnia konfigurację subdomeny `twin.kamilkuchta.pl` w Caddy.

## Rozwiązania

### Opcja 1: Użyj stabilnego linku CloudFront (najprostsze)

Link CloudFront **nie powinien się zmieniać** przy zwykłych deploymentach - zmienia się tylko gdy:
- Usuwasz i tworzysz nowy workspace (`terraform workspace new`)
- Uruchamiasz `terraform destroy`
- Coś wymusza recreate dystrybucji CloudFront

Sprawdź czy link faktycznie się zmienia:
```bash
cd terraform
terraform workspace select dev  # lub twój env
terraform output cloudfront_url
```

Jeśli przy kolejnych `terraform apply` (bez destroy) link jest ten sam - użyj go raz w Caddy i gotowe.

### Opcja 2: Skonfiguruj custom domain bezpośrednio na CloudFront

Terraform już ma wbudowaną obsługę custom domain (`use_custom_domain` w `variables.tf`).

Wymaga:
1. Dodania domeny `twin.kamilkuchta.pl` do konfiguracji
2. Utworzenia certyfikatu ACM w **us-east-1** (wymagane przez CloudFront)
3. Konfiguracji DNS (CNAME lub A record wskazujący na CloudFront)

Jeśli domena jest w Route53 - terraform może to zrobić automatycznie.
Jeśli domena jest u zewnętrznego registrara - trzeba ręcznie dodać CNAME.

### Opcja 3: Caddy jako reverse proxy z dynamicznym upstream

Jeśli naprawdę musisz mieć zmieniający się URL, w Caddy użyj zmiennej środowiskowej:

```caddy
twin.kamilkuchta.pl {
    reverse_proxy {$CLOUDFRONT_URL}
}
```

Lub plik z adresem aktualizowany po każdym deploy przez CI/CD.

## Rekomendacja

**Opcja 1** jeśli link CloudFront jest stabilny (sprawdź!).
**Opcja 2** jeśli chcesz pełną integrację - CloudFront bezpośrednio serwuje `twin.kamilkuchta.pl`.
