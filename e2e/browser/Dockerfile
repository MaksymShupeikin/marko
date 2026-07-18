FROM mcr.microsoft.com/playwright:v1.55.0-noble

WORKDIR /runner
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY run.mjs ./

CMD ["node", "run.mjs"]

