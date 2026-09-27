# Slim build of the official openwebwork/webwork2 Dockerfile (upstream has no
# published image on Docker Hub or GHCR, so upstream's own docs build it).
# Differences from upstream webwork2/Dockerfile (main):
#   - sources are cloned on the host by up.sh (the build has no git access), then COPYed
#   - the proxy CA is installed first so HTTPS works inside the build
# ponytail: TeX Live, fonts, dvipng/dvisvgm/pdf2svg/imagemagick dropped (~2 GB).
#   Hardcopy (PDF) and TeX-rendered images do not work. Our seeded problem is
#   plain text, and students' set list / set pages do not need them. Upgrade:
#   restore upstream's package list if an adapter ever needs hardcopy.
# ponytail: nodejs/npm from Ubuntu instead of nodesource (no extra HTTPS repo).
FROM mirror.gcr.io/library/ubuntu:26.04

ENV WEBWORK_URL=/webwork2 \
	WEBWORK_ROOT_URL=http://localhost:8081 \
	WEBWORK_SMTP_SERVER=localhost \
	WEBWORK_SMTP_SENDER=webwork@example.invalid \
	WEBWORK_TIMEZONE=America/Vancouver \
	APP_ROOT=/opt/webwork \
	DEBIAN_FRONTEND=noninteractive \
	DEBCONF_NONINTERACTIVE_SEEN=true
ENV WEBWORK_ROOT=$APP_ROOT/webwork2 \
	PG_ROOT=$APP_ROOT/pg \
	PATH=$PATH:$APP_ROOT/webwork2/bin

# The build host's egress is HTTPS-only through a TLS-re-terminating proxy, so
# apt is switched to https mirrors and told to trust the proxy CA before
# ca-certificates exists. Harmless on an open network (then pass no proxy args).
COPY ca.crt /usr/local/share/ca-certificates/fx-build-proxy.crt
ARG https_proxy
ARG no_proxy

RUN sed -i 's#http://#https://#g' /etc/apt/sources.list.d/ubuntu.sources \
	&& printf 'Acquire::https::CAInfo "/usr/local/share/ca-certificates/fx-build-proxy.crt";\nAcquire::Retries "10";\n' > /etc/apt/apt.conf.d/99fx-ca \
	&& apt-get update \
	&& for i in 1 2 3 4 5 6; do apt-get install -y --no-install-recommends --no-install-suggests \
	apt-utils ca-certificates cpanminus curl debconf-utils gcc git iputils-ping jq \
	libarchive-extract-perl libarchive-zip-perl libarray-utils-perl libc6-dev \
	libcapture-tiny-perl libclass-tiny-antlers-perl libclass-tiny-perl \
	libcpanel-json-xs-perl libcrypt-dev libcrypt-jwt-perl libcrypt-openssl-x509-perl \
	libcryptx-perl libdata-dump-perl libdata-structure-util-perl libdatetime-perl \
	libdatetime-format-xsd-perl libdatetime-hires-perl libdbd-mysql-perl \
	libdbd-mariadb-perl libdevel-checklib-perl libemail-address-xs-perl \
	libemail-date-format-perl libemail-sender-perl libemail-stuffer-perl \
	libexception-class-perl libextutils-config-perl libextutils-helpers-perl \
	libextutils-installpaths-perl libextutils-xsbuilder-perl libfile-copy-recursive-perl \
	libfile-find-rule-perl-perl libfile-sharedir-install-perl libfile-slurper-perl \
	libfuture-asyncawait-perl libgd-barcode-perl libgd-perl libhtml-scrubber-perl \
	libhtml-template-perl libhttp-async-perl libio-compress-perl libiterator-perl \
	libiterator-util-perl liblocale-maketext-lexicon-perl libmariadb-dev \
	libmath-random-secure-perl libmime-base32-perl libmime-tools-perl \
	libminion-backend-sqlite-perl libminion-perl libmodule-build-perl \
	libmodule-pluggable-perl libmojolicious-perl libmojolicious-plugin-renderfile-perl \
	libmoose-perl libmoosex-types-common-perl libmoosex-types-datetime-perl \
	libmoosex-types-perl libmoosex-types-uri-perl libnet-https-nb-perl libnet-ip-perl \
	libnet-ldap-perl libnet-oauth-perl libossp-uuid-perl libpadwalker-perl \
	libpandoc-wrapper-perl libpath-class-perl libpath-tiny-perl libperl-critic-perl \
	libphp-serialization-perl libsql-abstract-perl libssl-dev libstring-shellquote-perl \
	libsub-uplevel-perl libsvg-perl libtemplate-perl libtest-deep-perl \
	libtest-exception-perl libtest-fatal-perl libtest-mockobject-perl libtest-pod-perl \
	libtest-requires-perl libtest-warn-perl libtest-xml-perl libtext-csv-perl \
	libthrowable-perl libtimedate-perl libtypes-serialiser-perl libuniversal-can-perl \
	libuniversal-isa-perl liburi-encode-perl libuuid-tiny-perl libxml-generator-perl \
	libxml-parser-easytree-perl libxml-parser-perl libxml-semanticdiff-perl \
	libxml-simple-perl libxml-writer-perl libxml-xpath-perl libyaml-libyaml-perl \
	locales make mariadb-client netpbm patch ssl-cert sudo tzdata util-linux-extra \
	zlib1g-dev zip nodejs npm && break; sleep 3; done \
	&& command -v npm \
	&& update-ca-certificates && rm /etc/apt/apt.conf.d/99fx-ca \
	&& apt-get clean && rm -fr /var/lib/apt/lists/* /tmp/*

RUN cpanm -n Perl::Tidy@20260204 Archive::Zip::SimpleZip Net::SAML2 \
	&& rm -fr ./cpanm /root/.cpanm /tmp/*

RUN mkdir -p $APP_ROOT/courses $APP_ROOT/libraries $APP_ROOT/libraries/webwork-open-problem-library $APP_ROOT/webwork2 /www/www/html
COPY webwork2 $APP_ROOT/webwork2
COPY pg $APP_ROOT/pg

RUN echo "PATH=$PATH:$APP_ROOT/webwork2/bin" >> /root/.bashrc \
	&& mkdir -p /run/webwork2 /etc/ssl/local \
	&& cd $APP_ROOT/webwork2/ \
		&& chown www-data DATA ../courses logs tmp /etc/ssl/local /run/webwork2 \
		&& chmod -R u+w DATA ../courses logs tmp /run/webwork2 /etc/ssl/local \
	&& echo "en_US ISO-8859-1\nen_US.UTF-8 UTF-8" > /etc/locale.gen \
		&& /usr/sbin/locale-gen \
		&& echo "locales locales/default_environment_locale select en_US.UTF-8\ndebconf debconf/frontend select Noninteractive" > /tmp/preseed.txt \
		&& debconf-set-selections /tmp/preseed.txt \
	&& rm -f /etc/localtime /etc/timezone && echo "Etc/UTC" > /etc/timezone \
		&& dpkg-reconfigure -f noninteractive tzdata \
	&& cd $WEBWORK_ROOT/htdocs && npm install \
	&& cd $PG_ROOT/htdocs && npm install \
	&& rm -rf /root/.npm

# ponytail: no Open Problem Library. An empty OpenProblemLibrary dir and a stub
# tagging-taxonomy.json stop upstream's entrypoint from cloning the OPL (~850 MB)
# and running OPL-update. The library browser is therefore empty. Upgrade: mount
# a real OPL volume and delete these two lines.
RUN mkdir -p $APP_ROOT/libraries/webwork-open-problem-library/OpenProblemLibrary \
	&& mkdir -p $WEBWORK_ROOT/htdocs/DATA && echo "[]" > $WEBWORK_ROOT/htdocs/DATA/tagging-taxonomy.json

EXPOSE 8080
WORKDIR $WEBWORK_ROOT
COPY webwork2/docker-config/docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["docker-entrypoint.sh"]
ENV SSL=0 PAPERSIZE=letter SYSTEM_TIMEZONE=UTC ADD_LOCALES=0 ADD_APT_PACKAGES=0
CMD ["sudo", "-E", "-u", "www-data", "hypnotoad", "-f", "bin/webwork2"]

# Upstream's entrypoint runs `dpkg-reconfigure libpaper2` under `set -e`;
# upstream gets libpaper2 via TeX Live, so the slim build installs it explicitly.
RUN sed -i 's#http://#https://#g' /etc/apt/sources.list.d/ubuntu.sources \
	&& apt-get -o Acquire::Retries=10 update \
	&& apt-get install -y --no-install-recommends libpaper2 \
	&& apt-get clean && rm -fr /var/lib/apt/lists/*
LABEL fx.provider=webwork
