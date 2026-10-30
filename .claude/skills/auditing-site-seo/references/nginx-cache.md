# nginx cache + redirect config

Two things belong in nginx, not Traefik: `Cache-Control` (path-dependent) and
absolute/relative redirects. Traefik keeps TLS, HSTS and security headers.

## Static site served from this repo (`achim-hoefer` style)

File: `<service>/nginx/default.conf`, mounted over the image's default:

```yaml
volumes:
  - ./serve:/usr/share/nginx/html
  - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
```

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    charset utf-8;

    # Keep nginx from building absolute Location headers from the internal
    # port-80 origin — otherwise a directory redirect hands out http:// URLs
    # and costs every internal hop an extra round trip.
    absolute_redirect off;

    gzip on;
    gzip_vary on;
    gzip_min_length 512;
    gzip_types text/css text/plain application/json application/xml image/svg+xml;

    location ~* \.html$ {
        add_header Cache-Control "public, max-age=0, must-revalidate" always;
        try_files $uri =404;           # never `=404` -> /index.html (soft-404s)
    }
    location /public/fonts/ {
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files $uri =404;
    }
    location = /public/plan.css {      # unhashed CSS that changes: short TTL
        add_header Cache-Control "public, max-age=3600" always;
        try_files $uri =404;
    }
    location /public/ {
        add_header Cache-Control "public, max-age=604800" always;
        try_files $uri =404;
    }
    location ~ ^/(robots\.txt|sitemap\.xml|llms\.txt)$ {
        add_header Cache-Control "public, max-age=3600" always;
        try_files $uri =404;
    }
    location / {
        add_header Cache-Control "public, max-age=0, must-revalidate" always;
        try_files $uri $uri/ =404;
    }
}
```

## Astro site built in its own repo (`bumbleflies` style)

File: `nginx.conf` in the source repo, `COPY`d into the image. Same rules, plus
two static-site traps worth checking on sight:

- **`try_files $uri $uri/ /index.html`** — an SPA fallback copied onto a static
  site. Every typo'd or legacy URL then returns **200 with the homepage**.
  Google sees infinite duplicates and burns crawl budget. Use `=404`.
  Verify: `curl -o /dev/null -w '%{http_code}' <base>/definitely-not-a-page/`
  → must be 404, never 200.
- **Missing `404.html`** — Astro only emits it if `src/pages/404.astro` exists.
  An `error_page 404 /404.html` pointing at nothing shows bare nginx instead of
  your branded page.

Add `src/pages/404.astro` so the fallback has somewhere to land.

## The immutable rule

| Asset | May use `immutable`? |
|---|---|
| Hashed build output (`/_astro/x.abc123.css`) | yes |
| Fonts, if renamed on replacement | yes |
| `public/images/*`, unhashed CSS | **no** — name never changes, so a year-long cache means a year-long stale file |

`immutable` promises the bytes at that URL never change. If the filename stays
put, that promise is false the first time you update the file.

## Before deploying

A broken config means the container won't start, Traefik pulls the routers and
the site is gone. Validate against the real image first:

```bash
docker run --rm -v "$PWD/nginx/default.conf":/etc/nginx/conf.d/default.conf:ro \
  nginx:stable nginx -t
```

Then, for behaviour rather than syntax, run a throwaway container against the
real content on a spare port:

```bash
docker run --rm -d --name cachetest -p 127.0.0.1:8899:80 \
  -v "$PWD/serve":/usr/share/nginx/html:ro \
  -v "$PWD/nginx/default.conf":/etc/nginx/conf.d/default.conf:ro nginx:stable
for p in / /public/plan.css /public/fonts/<f>.woff2; do
  curl -sSI -A healthcheck "http://127.0.0.1:8899$p" | grep -iE '^HTTP|cache-control'
done
docker stop cachetest
```

`add_header` does **not** inherit: once a `location` sets its own, server-level
`add_header` stops applying to it. Repeat it in every block.
