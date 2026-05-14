FROM node:22-alpine

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY apps/web/ /app/

EXPOSE 3000
CMD ["npm", "run", "dev"]
