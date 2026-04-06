FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

FROM node:20-alpine AS production
RUN apk add --no-cache git
WORKDIR /app
RUN addgroup -g 1001 -S lumis && adduser -S lumis -u 1001
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY package.json .
USER lumis
EXPOSE 3000
CMD ["node", "dist/index.js"]
