#!/bin/bash
# Copia arquivos necessários do frontend para cá
cp ../frontend/socio.html ./
cp ../frontend/sw-socio.js ./
cp ../frontend/manifest-socio.json ./
mkdir -p assets/css assets/js assets/img
cp ../frontend/assets/css/*.css ./assets/css/
cp ../frontend/assets/js/*.js ./assets/js/
cp -r ../frontend/assets/img ./assets/