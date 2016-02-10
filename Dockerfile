FROM sdp-ingest5.kat.ac.za:5000/docker-base

MAINTAINER Ludwig Schwardt "ludwig@ska.ac.za"

# Install Python dependencies
COPY requirements.txt /tmp/install/requirements.txt
RUN install-requirements.py --default-versions ~/docker-base/base-requirements.txt -r /tmp/install/requirements.txt

# Install the current package
COPY . /tmp/install/kattelmod
WORKDIR /tmp/install/kattelmod
RUN python ./setup.py clean && pip install --no-index .

# Network setup
EXPOSE 8888

# Launch configuration
WORKDIR /home/kat
COPY ./kattelmod /home/kat
USER root
RUN chown -R kat:kat /home/kat/
USER kat
RUN pip install jupyter
 # way too much effort to include all of the notebook dependencies in the requirements file
RUN pip install matplotlib

USER root
ADD https://github.com/krallin/tini/releases/download/v0.9.0/tini /usr/bin/tini
RUN chmod +x /usr/bin/tini
USER kat
ENTRYPOINT ["/usr/bin/tini", "--"]
