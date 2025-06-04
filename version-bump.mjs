import fs from 'fs';
import path from 'path';

// Read version from manifest.json
const manifestPath = path.join(process.cwd(), 'manifest.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const currentVersion = manifest.version;

// Read versions.json or initialize if it doesn't exist
const versionsPath = path.join(process.cwd(), 'versions.json');
let versions = {};
if (fs.existsSync(versionsPath)) {
    versions = JSON.parse(fs.readFileSync(versionsPath, 'utf8'));
}

// Update versions.json with the current version and minAppVersion
versions[currentVersion] = manifest.minAppVersion;

// Write updated versions.json
fs.writeFileSync(versionsPath, JSON.stringify(versions, null, '\t')); // Using tabs for indentation

console.log(`Updated versions.json with version ${currentVersion}`);

// Example: How to use with npm version
// "scripts": {
//   "version": "node version-bump.mjs && git add manifest.json versions.json"
// }
// Then run: npm version patch (or minor, major)