# Reverse Proxy Examples

이 프로젝트의 [api_routes.py](api_routes.py) 기준 보안 모델은 아래 두 단계입니다.

1. 애플리케이션 내부 제한
- `/api/dashboard-stream`은 기본적으로 내부망 또는 loopback IP만 허용합니다.
- `HACCP_STREAM_TOKEN`을 설정하면 `?stream_token=`으로도 인증할 수 있습니다.
- `HACCP_REQUIRE_STREAM_TOKEN=1`이면 내부 IP라도 토큰 없이는 거부합니다.

2. Reverse proxy 제한
- 운영에서는 Flask/Dash를 인터넷에 직접 노출하지 말고 reverse proxy 뒤에 둡니다.
- reverse proxy에서 `/api/dashboard-stream`만 별도로 제한합니다.
- SSE이므로 proxy buffering을 끄고 keep-alive를 유지합니다.

## Recommended Environment Variables

```env
HACCP_STREAM_TOKEN=replace-with-long-random-token
HACCP_REQUIRE_STREAM_TOKEN=1
```

권장 방식은 다음과 같습니다.

- 외부 사용자는 reverse proxy까지만 접근 가능
- reverse proxy는 `/api/dashboard-stream`에 대해 사내 IP만 허용
- 브라우저는 내부 페이지에서만 `stream_token`을 받아 SSE 연결

## Nginx Example

아래 예시는 `127.0.0.1:8050`에서 실행 중인 Dash/Flask로 프록시하고,
`/api/dashboard-stream`은 사내망만 허용하는 설정입니다.

```nginx
server {
    listen 443 ssl http2;
    server_name haccp.example.internal;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8050;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/dashboard-stream {
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        deny all;

        proxy_pass http://127.0.0.1:8050/api/dashboard-stream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
        chunked_transfer_encoding off;
        add_header X-Accel-Buffering no;
    }
}
```

## Nginx Concrete Config For Current Workspace

현재 저장소에서 확인되는 내부 API 기본 주소는 [pages/main_helpers.py](pages/main_helpers.py#L104)의 `http://192.168.0.30:5000`입니다.
hostname 정보는 저장소에 없어서, 현재 운영 진입점도 같은 내부 IP를 쓴다는 가정으로 아래처럼 바로 적용 가능한 완성본을 둘 수 있습니다.

- reverse proxy 진입 주소: `192.168.0.30`
- 허용 사내 대역: `192.168.0.0/24`
- Dash/Flask upstream: `127.0.0.1:8050`

```nginx
server {
  listen 80;
  server_name 192.168.0.30;

  location / {
    proxy_pass http://127.0.0.1:8050;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
  }

  location /api/dashboard-stream {
    allow 127.0.0.1;
    allow 192.168.0.0/24;
    deny all;

    proxy_pass http://127.0.0.1:8050/api/dashboard-stream?$query_string;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
    chunked_transfer_encoding off;
    add_header X-Accel-Buffering no;
  }
}
```

토큰 강제를 같이 쓰려면 운영 환경변수는 아래처럼 맞추면 됩니다.

```env
HACCP_STREAM_TOKEN=replace-with-long-random-token
HACCP_REQUIRE_STREAM_TOKEN=1
```

이 구성의 의미는 다음과 같습니다.

- `192.168.0.30`으로 들어온 일반 페이지 요청은 모두 로컬 Dash로 프록시
- `/api/dashboard-stream`은 `192.168.0.0/24` 대역과 loopback만 허용
- 앱 내부에서는 추가로 `stream_token`까지 검증하므로 프록시와 앱이 이중 방어를 구성

### Nginx Strict Token Variant

토큰까지 프록시 단계에서 강제하려면 query string을 검사할 수 있습니다.

```nginx
location /api/dashboard-stream {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;

    if ($arg_stream_token = "") {
        return 401;
    }

    proxy_pass http://127.0.0.1:8050/api/dashboard-stream?$query_string;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
}
```

실제 토큰값 비교까지 Nginx에서 하려면 `map`, `auth_request`, 또는 WAF 연동이 더 적절합니다. 일반적으로는 현재 코드처럼 앱에서 토큰 검증을 유지하고, 프록시는 IP 제한만 맡기는 편이 단순합니다.

## IIS + ARR Example

전제:

- IIS에 `Application Request Routing`과 `URL Rewrite`가 설치되어 있어야 합니다.
- Dash/Flask 앱은 로컬에서 `http://127.0.0.1:8050`으로 실행합니다.

다음 [web.config](web.config) 예시는 IIS가 전체 트래픽을 로컬 Dash로 프록시하면서,
`/api/dashboard-stream`만 내부 IP 대역 또는 loopback만 허용하는 방식입니다.

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="Allow dashboard stream only from internal networks" stopProcessing="true">
          <match url="^api/dashboard-stream$" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REMOTE_ADDR}" pattern="^127\.0\.0\.1$|^::1$|^10\.|^192\.168\.|^172\.(1[6-9]|2[0-9]|3[0-1])\." negate="true" />
          </conditions>
          <action type="CustomResponse" statusCode="401" statusReason="Unauthorized" statusDescription="Internal network only" />
        </rule>

        <rule name="Proxy dashboard stream" stopProcessing="true">
          <match url="^api/dashboard-stream$" />
          <action type="Rewrite" url="http://127.0.0.1:8050/api/dashboard-stream" appendQueryString="true" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_FOR" value="{REMOTE_ADDR}" />
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
          </serverVariables>
        </rule>

        <rule name="Proxy all other requests" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8050/{R:1}" appendQueryString="true" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_FOR" value="{REMOTE_ADDR}" />
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
          </serverVariables>
        </rule>
      </rules>
    </rewrite>

    <httpProtocol>
      <customHeaders>
        <add name="X-Accel-Buffering" value="no" />
      </customHeaders>
    </httpProtocol>
  </system.webServer>
</configuration>
```

### IIS Notes

- ARR proxy response buffering은 가능하면 끄는 편이 안전합니다.
- IIS 서버 자체를 인터넷에 노출한다면 Windows Firewall에서도 `/api/dashboard-stream` 접근 대역을 한 번 더 제한하는 편이 좋습니다.
- `HTTP_X_FORWARDED_FOR`는 신뢰된 IIS proxy 앞단에서만 설정되게 유지해야 합니다.

## Recommended Operations Checklist

1. Flask/Dash는 `127.0.0.1`에만 바인딩합니다.
2. reverse proxy에서 `/api/dashboard-stream`에 내부망 제한을 겁니다.
3. 앱 환경변수에 `HACCP_STREAM_TOKEN`과 `HACCP_REQUIRE_STREAM_TOKEN=1`을 설정합니다.
4. 공인 인터넷에서 앱 포트 `8050` 직접 접근은 방화벽으로 차단합니다.
5. reverse proxy 로그에서 `/api/dashboard-stream` 401 발생을 모니터링합니다.

## Why This Matches The Current Code

[api_routes.py](api_routes.py)의 `_get_request_ip()`는 `X-Forwarded-For`를 우선 사용하고,
`_is_stream_authorized()`는 다음 순서로 검사합니다.

1. `stream_token`이 유효하면 허용
2. `HACCP_REQUIRE_STREAM_TOKEN=1`인데 토큰이 틀리면 거부
3. 그 외에는 내부망 또는 loopback IP만 허용

즉, reverse proxy는 네트워크 경계를 만들고, 앱은 최종 안전장치 역할을 합니다.