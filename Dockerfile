FROM node:20-alpine
WORKDIR /app
COPY . .
EXPOSE 3006
CMD ["npm", "start"]
