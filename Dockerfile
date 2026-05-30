# Use the official Microsoft Playwright Python base image
FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

# Set the working directory inside the container
WORKDIR /app

# Copy requirements file first to leverage Docker build cache
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files into the container
COPY . .

# Expose the port (Railway will override this with the dynamic PORT variable)
EXPOSE 8080

# Start the server daemon
CMD ["python", "dashboard_server.py"]
