# RedCouncil Deployment Manual: Alibaba Cloud (Ubuntu 24.04)

This guide covers the end-to-end deployment of the RedCouncil project on Alibaba Cloud Elastic Compute Service (ECS) running Ubuntu 24.04 LTS. It includes setting up PostgreSQL, configuring a domain name with SSL, and integrating Alibaba Cloud Object Storage Service (OSS) for permanent attachment storage.

---

## 1. Provisioning the ECS Instance

1. Log in to the [Alibaba Cloud ECS Console](https://ecs.console.aliyun.com/).
2. Click **Create Instance**.
3. **Billing Method**: Choose Pay-As-You-Go or Subscription based on your needs.
4. **Image**: Select **Ubuntu 24.04 LTS** (64-bit).
5. **Instance Type**: 2 vCPUs and 4 GiB memory (e.g., `ecs.g7.large`) is a good starting point. 
6. **Storage**: At least 40 GiB ESSD. 
7. **Public IP**: Ensure "Assign Public IPv4 Address" is checked and set an appropriate bandwidth peak.
8. **Security Group**: Create or select a security group and open the following inbound ports:
   - **SSH (22/TCP)**: Restrict to your IP if possible.
   - **HTTP (80/TCP)**: 0.0.0.0/0 (For Let's Encrypt and web traffic)
   - **HTTPS (443/TCP)**: 0.0.0.0/0 (For secure web traffic)
9. **Login Credentials**: Set a Key Pair (recommended) or a strong root password.
10. Click **Create Order**.

---

## 2. Server Preparation & System Dependencies

Connect to your instance via SSH:
```bash
ssh root@<your_ecs_public_ip>
```

Update the system and install required tools (PostgreSQL, Nginx, Certbot, Python, Node.js):

```bash
# Update package list
sudo apt-get update && sudo apt-get upgrade -y

# Install Python and build tools
sudo apt-get install -y python3 python3-pip python3-venv git curl build-essential

# Install Nginx and Certbot
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Install Node.js (for frontend build)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

---

## 3. Installing & Configuring PostgreSQL

While you can run Postgres via the included `docker-compose.yml`, installing it natively on Ubuntu is straightforward and performs well for bare-metal deployments.

```bash
# Install PostgreSQL 16
sudo apt-get install -y postgresql postgresql-contrib

# Start and enable the service
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

Set up the database and user for RedCouncil:

```bash
sudo -u postgres psql
```

Inside the `psql` prompt, run:
```sql
CREATE DATABASE redcouncil;
CREATE USER redcouncil WITH ENCRYPTED PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE redcouncil TO redcouncil;
ALTER DATABASE redcouncil OWNER TO redcouncil;
\q
```

*Note: You will use these credentials in the backend `.env` file.*

---

## 4. Alibaba Cloud OSS Configuration (Permanent Storage)

RedCouncil uses OSS to store original uploaded files permanently. 

1. Go to the [Alibaba Cloud OSS Console](https://oss.console.aliyun.com/).
2. Click **Create Bucket**.
   - **Bucket Name**: e.g., `redcouncil-attachments`
   - **Region**: Select the same region as your ECS instance to save on transfer costs and reduce latency.
   - **Endpoint**: Note the endpoint (e.g., `oss-ap-southeast-1.aliyuncs.com`).
   - **ACL**: Private (files should only be accessible via the app).
3. Create a **RAM User** in the IAM console:
   - Grant the user programmatic access (AccessKey ID & Secret).
   - Attach the `AliyunOSSFullAccess` policy (or a custom policy scoped to the bucket).
   - Save the **AccessKey ID** and **AccessKey Secret**.

---

## 5. Deploying the Application

### Clone the Repository
```bash
cd /opt
sudo git clone https://github.com/your-org/redcouncil.git
sudo chown -R $USER:$USER redcouncil
cd redcouncil
```

### Backend Setup

1. Navigate to the backend directory and set up a virtual environment:
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment variables. Create a `.env` file:
```bash
cp .env.example .env
nano .env
```

3. Update the `.env` file with your production values:
```env
# Database (use the credentials created in Step 3)
DATABASE_URL=postgresql://redcouncil:your_secure_password@localhost:5432/redcouncil

# Alibaba Cloud OSS
OSS_ACCESS_KEY_ID=your_ram_access_key
OSS_ACCESS_KEY_SECRET=your_ram_secret
OSS_ENDPOINT=https://oss-ap-southeast-1.aliyuncs.com # Match your bucket region
OSS_BUCKET_NAME=redcouncil-attachments

# Security & App Config
QWEN_API_KEY=your_qwen_api_key
CLERK_ISSUER=https://your-app.clerk.accounts.dev
CORS_ALLOWED_ORIGINS=https://yourdomain.com
```

4. Run the backend using `systemd` or PM2 (or just background it for testing):
```bash
# Start backend on port 8000
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd ../frontend
npm install
```

2. Configure frontend environment variables:
```bash
cp .env.example .env
nano .env
```
Ensure `VITE_API_URL` points to your domain (e.g., `https://yourdomain.com/api`).

3. Build the frontend:
```bash
npm run build
```
The static files will be placed in `frontend/dist/`.

---

## 6. Domain Name and SSL (Nginx & Certbot)

1. **DNS Setup**: In your domain registrar, create an `A Record` pointing your domain (e.g., `redcouncil.yourdomain.com`) to the **ECS Public IP**.

2. Configure Nginx. Create a new site config:
```bash
sudo nano /etc/nginx/sites-available/redcouncil
```

Paste the following configuration:
```nginx
server {
    listen 80;
    server_name yourdomain.com; # Replace with your domain

    # Serve Frontend static files
    location / {
        root /opt/redcouncil/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Proxy API requests to FastAPI backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Support Server-Sent Events (SSE)
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

3. Enable the site and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/redcouncil /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

4. **Obtain SSL Certificate**: Run Certbot to automatically configure HTTPS.
```bash
sudo certbot --nginx -d yourdomain.com
```
Certbot will automatically modify your Nginx configuration to enable SSL and set up a cron job for certificate renewal.

---

## 7. Process Management (Keeping the Backend Alive)

To ensure the backend runs continuously and restarts on reboot, use a `systemd` service.

1. Create a service file:
```bash
sudo nano /etc/systemd/system/redcouncil-backend.service
```

2. Add the following content:
```ini
[Unit]
Description=RedCouncil FastAPI Backend
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=/opt/redcouncil/backend
ExecStart=/opt/redcouncil/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable redcouncil-backend
sudo systemctl start redcouncil-backend
sudo systemctl status redcouncil-backend
```

Your RedCouncil application should now be live, secure, and fully operational on Alibaba Cloud!
