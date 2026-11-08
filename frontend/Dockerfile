# Dev server (Vite) for the local prototype: `docker compose up` serves http://localhost:5173.
# Vite proxies /api to the backend (VITE_API_URL, set to http://backend:8000 in compose).
FROM node:20-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
