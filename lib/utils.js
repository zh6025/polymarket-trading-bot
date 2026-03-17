// lib/utils.js

// Utility functions for HTTP requests, decompression, and logging.

/**
 * Performs a GET request to the specified URL.
 * @param {string} url - The URL to send the request to.
 * @returns {Promise<any>} - The response data.
 */
async function httpGet(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error('Network response was not ok ' + response.statusText);
    }
    return await response.json();
}

/**
 * Decompresses data using the specified algorithm.
 * @param {Buffer} compressedData - The compressed data.
 * @param {string} algorithm - The algorithm to use for decompression (e.g., 'gzip').
 * @returns {Buffer} - The decompressed data.
 */
function decompressData(compressedData, algorithm) {
    const zlib = require('zlib');
    switch (algorithm) {
        case 'gzip':
            return zlib.gunzipSync(compressedData);
        case 'deflate':
            return zlib.inflateSync(compressedData);
        default:
            throw new Error('Unsupported compression algorithm');
    }
}

/**
 * Logs messages to the console with timestamp.
 * @param {...any} messages - The messages to log.
 */
function log(...messages) {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}]`, ...messages);
}

/**
 * Utility function to check if a value is a number.
 * @param {*} value - The value to check.
 * @returns {boolean} - True if the value is a number, otherwise false.
 */
function isNumber(value) {
    return typeof value === 'number' && !isNaN(value);
}

module.exports = { httpGet, decompressData, log, isNumber };