FROM sdp-docker-registry.kat.ac.za:5000/docker-base:xenial

MAINTAINER Ludwig Schwardt "ludwig@ska.ac.za"

# Install Python dependencies
COPY requirements.txt /tmp/install/requirements.txt
RUN install-requirements.py --default-versions ~/docker-base/base-requirements.txt -r /tmp/install/requirements.txt

# Install the current package
COPY . /tmp/install/kattelmod
WORKDIR /tmp/install/kattelmod
RUN python ./setup.py clean && pip install --no-index .

# Expose Jupyter port
EXPOSE 8888

# Launch configuration
WORKDIR /home/kat
COPY ./kattelmod /home/kat
USER root
RUN chown -R kat:kat /home/kat/
USER kat
