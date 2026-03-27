# Use an official Python runtime as a parent image
FROM python:3.10

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install Java runtime environment
RUN apt update && apt install default-jre -y

# Install any needed packages specified in requirements.txt
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

RUN ["python", "-m", "pip", "install", "flask"]
# Expose port 8080 to allow communication to/from server
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
