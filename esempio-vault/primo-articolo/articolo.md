---
title: Come installare WordPress in 5 minuti
date: 2024-03-10
tags: [wordpress, tutorial, hosting]
categories: [Guide, WordPress]
status: publish
author: mario
excerpt: Guida rapida per installare WordPress sul tuo server in pochi passi.
---

# Come installare WordPress in 5 minuti

WordPress è il CMS più usato al mondo. In questa guida ti mostro come installarlo rapidamente.

## Requisiti

Prima di iniziare assicurati di avere:

- PHP 8.0 o superiore
- MySQL 5.7 o MariaDB 10.3
- Apache o Nginx

## Passo 1: Scarica WordPress

Vai su [wordpress.org](https://wordpress.org/download/) e scarica l'ultima versione.

## Passo 2: Configura il database

Crea un database MySQL con questi comandi:

```sql
CREATE DATABASE mio_blog;
CREATE USER 'utente'@'localhost' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON mio_blog.* TO 'utente'@'localhost';
```

## Passo 3: Carica i file

Estrai l'archivio e carica i file sul server via FTP o SSH.

## Conclusione

Hai installato WordPress con successo! Ora puoi personalizzarlo con temi e plugin.

> **Suggerimento**: Installa subito un plugin di sicurezza come Wordfence.
