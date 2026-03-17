"use strict";

const https = require("https");
const zlib = require("zlib");

const agent = new https.Agent({ keepAlive: true });