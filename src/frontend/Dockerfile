# Forge SPA (ADR-007), packaged for the reference deployment (ADR-009).
#
# Two stages. `npm run build` type-checks (`tsc --noEmit`) and bundles; nginx serves the
# result as static files. Phase 5.1 replaced the Vite **dev server** that used to run
# here — see nginx/default.conf.template for how the one environment-dependent value
# (the API's address as the browser sees it) is supplied at container start instead of
# being inlined at build time, which is what lets this image stay the same artifact
# across the evaluator's laptop and any cloud environment.

FROM node:24-alpine AS build

WORKDIR /app

# Dependencies first: the layer is cached until package.json or the lockfile changes.
# `npm ci` installs the locked tree exactly — a build is reproducible or it is anecdote.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Fails the image build on a type error, so a broken SPA cannot reach a container.
RUN npm run build

FROM nginx:1.29-alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template

# Only FORGE_* is expanded in the template; nginx's own $uri, $host and friends are not
# environment variables and must survive verbatim.
ENV NGINX_ENVSUBST_FILTER="^FORGE_"

# Sensible standalone defaults: this image serves a working SPA against a Forge API on
# the same host with no configuration at all. deploy/docker-compose.yml sets both.
ENV FORGE_API_BASE_URL="http://localhost:8000" \
    FORGE_ROLE="configurator"

EXPOSE 80
