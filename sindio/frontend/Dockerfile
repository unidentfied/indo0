# syntax=docker/dockerfile:1

# ---------- Builder ----------
FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy source files
COPY . ./

# Build the application (tsc typecheck is done in frontend.yml CI)
RUN npx vite build

# ---------- Runtime ----------
FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
