FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        apache2 \
        openssh-server \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create admin user and home directory
RUN useradd -m -s /bin/bash admin

# Drop the credentials file into the admin home directory
COPY credentials.json /home/admin/credentials.json
RUN chown admin:admin /home/admin/credentials.json \
    && chmod 644 /home/admin/credentials.json \
    && chmod 755 /home/admin

# Apache: replace default vhost and static files
COPY apache.conf /etc/apache2/sites-available/000-default.conf
COPY robots.txt /var/www/html/robots.txt
COPY index.html /var/www/html/index.html

# Enable modules needed for the demo misconfigurations
RUN a2enmod status autoindex

# SSH requires this directory at runtime
RUN mkdir -p /run/sshd

COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 22 80

CMD ["/start.sh"]
