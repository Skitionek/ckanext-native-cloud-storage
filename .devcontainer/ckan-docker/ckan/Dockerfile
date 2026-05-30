FROM ckan/ckan-base:2.11

# Install any extensions needed by your CKAN instance
# See Dockerfile.dev for more details and examples

# Copy custom initialization scripts
COPY --chown=ckan-sys:ckan-sys docker-entrypoint.d/* /docker-entrypoint.d/

# Apply any patches needed to CKAN core or any of the built extensions (not the
# runtime mounted ones)
COPY --chown=ckan-sys:ckan-sys patches ${APP_DIR}/patches

USER ckan

WORKDIR ${APP_DIR}

RUN for d in "${APP_DIR}"/patches/*; do \
        if [ -d "$d" ]; then \
            for f in "$d"/*.patch; do \
                [ -f "$f" ] || continue; \
                echo "Dockerfile: Applying patch $f to ${SRC_DIR}/$(basename "$d")"; \
                patch -d "${SRC_DIR}/$(basename "$d")" -p1 < "$f"; \
            done; \
        fi ; \
    done
