# syntax=docker/dockerfile:1

# Tributary reader. The browser talks to this Next.js server only: /api/* is
# rewritten to the API service, so the bundle needs no public API host and
# there is no CORS hop. The rewrite targets the compose service named `api`;
# renaming that service (or running the image outside the shipped compose file)
# requires rebuilding with a different API_PROXY_TARGET.

FROM node:22-alpine AS deps

RUN npm install --global pnpm@12.8.1

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile


FROM node:22-alpine AS builder

RUN npm install --global pnpm@12.8.1

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# Docker-only build switches. A hosted build leaves all three unset, so Vercel
# keeps its default output and the browser keeps calling the absolute API URL.
#   NEXT_OUTPUT=standalone  emit the self-contained server bundle
#   API_PROXY_TARGET        rewrite /api/* to the compose service named `api`
#   NEXT_PUBLIC_API_BASE    "/" collapses to a same-origin base in lib/api.ts
# A literal empty value is not usable here: Next deletes empty variables while
# loading the build environment, which would fall back to localhost:8000.
ARG NEXT_OUTPUT=standalone
ARG API_PROXY_TARGET=http://api:8000
ARG NEXT_PUBLIC_API_BASE=/
ENV NEXT_OUTPUT=${NEXT_OUTPUT} \
    API_PROXY_TARGET=${API_PROXY_TARGET} \
    NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build


FROM node:22-alpine AS runner

LABEL org.opencontainers.image.title="Tributary Reader" \
      org.opencontainers.image.description="Self-hosted feed reader and pipe builder" \
      org.opencontainers.image.source="https://github.com/Ekomjah/tributary"

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup --system --gid 10001 nodejs \
    && adduser --system --uid 10001 --ingroup nodejs nextjs

WORKDIR /app

# Standalone output carries its own minimal node_modules and server.js.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]

CMD ["node", "server.js"]
