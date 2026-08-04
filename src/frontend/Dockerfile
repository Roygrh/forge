# Forge SPA (ADR-007), packaged for the reference deployment (ADR-009).
#
# This image runs Vite's **dev server**, not a static build behind nginx. That is a
# deliberate Phase 3.3 choice: the SPA's one environment-dependent value
# (VITE_API_BASE_URL) is inlined at *build* time by Vite, so a production image would
# have to be rebuilt for every environment it is pointed at. The dev server reads it at
# start-up instead, which keeps `docker compose up` a single command that works on any
# host. The static build (`npm run build`) is what a real deployment ships, and swapping
# this stage for nginx is the change to make when there is a real environment to ship to.

FROM node:24-alpine

WORKDIR /app

# Dependencies first: the layer is cached until package.json or the lockfile changes.
# `npm ci` installs the locked tree exactly — a build is reproducible or it is anecdote.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0 so the published port is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
