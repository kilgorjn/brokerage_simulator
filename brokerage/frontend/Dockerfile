FROM nginx:alpine

WORKDIR /etc/nginx

# Copy custom nginx configuration
COPY nginx.conf conf.d/default.conf

# Copy static files (HTML)
COPY index.html /usr/share/nginx/html/

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
