#!/usr/bin/env tsx

/**
 * Send commit notification for Parts MCP submodule
 * This script is called from GitHub Actions workflow
 */

interface CommitData {
  commit_message: string;
  commit_sha: string;
  commit_url: string;
  author_name: string;
  author_email: string;
  repository: string;
  branch: string;
  timestamp: string;
  service_name?: string;
  service_emoji?: string;
}

/**
 * Get commit data from environment variables
 */
function getCommitData(): CommitData {
  return {
    commit_message: process.env.COMMIT_MESSAGE || 'No message',
    commit_sha: process.env.COMMIT_SHA || '',
    commit_url: process.env.COMMIT_URL || '',
    author_name: process.env.AUTHOR_NAME || 'Unknown',
    author_email: process.env.AUTHOR_EMAIL || '',
    repository: process.env.REPOSITORY || 'Unknown',
    branch: process.env.BRANCH || 'main',
    timestamp: process.env.TIMESTAMP || new Date().toISOString(),
    service_name: process.env.SERVICE_NAME || 'Parts MCP',
    service_emoji: process.env.SERVICE_EMOJI || '🤖',
  };
}

/**
 * Send notification via API endpoint
 */
async function sendNotification() {
  try {
    const apiKey = process.env.GITHUB_API_KEY;

    if (!apiKey) {
      console.error('❌ Error: GITHUB_API_KEY environment variable is not set');
      console.error('   Please set the GITHUB_API_KEY in your environment');
      process.exit(1);
    }

    const data = getCommitData();
    const apiUrl = 'https://source.parts/api/notify/github';

    // Display formatted notification info
    console.log(`${data.service_emoji} Sending ${data.service_name} commit notification...`);
    console.log(`   📦 Repository: ${data.repository}`);
    console.log(`   🌿 Branch: ${data.branch}`);
    console.log(`   👤 Author: ${data.author_name}`);
    console.log(`   🔗 URL: ${apiUrl}`);
    console.log(`   🤖 Service: ${data.service_name}`);

    // Show first line of commit message
    const firstLine = data.commit_message.split('\n')[0].trim();
    const truncatedMessage = firstLine.length > 60
      ? firstLine.substring(0, 57) + '...'
      : firstLine;
    console.log(`   📝 Message: ${truncatedMessage}`);

    // Show API key is set (without revealing it)
    console.log(`   🔑 API Key: Set (${apiKey.length} chars)`);
    console.log('');

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-github-api-key': apiKey,
      },
      body: JSON.stringify(data),
    });

    const responseData = await response.text();
    const statusText = `${response.status} ${response.statusText}`;

    if (!response.ok) {
      console.error(`❌ Failed to send ${data.service_name} notification!`);
      console.error(`   Status: ${statusText}`);
      console.error(`   📊 Response Status: ${statusText}`);
      console.error(`   Response: ${responseData}`);

      let parsedError;
      try {
        parsedError = JSON.parse(responseData);
        console.error(`   Error: ${parsedError.error || 'Unknown error'}`);
      } catch {
        // Not JSON, already logged above
      }

      process.exit(1);
    }

    let parsedResponse;
    try {
      parsedResponse = JSON.parse(responseData);
    } catch {
      // Response might not be JSON
      parsedResponse = { message: responseData };
    }

    console.log(`✅ ${data.service_name} notification sent successfully!`);
    console.log(`   📊 Response Status: ${statusText}`);

    if (parsedResponse.email_id) {
      console.log(`   📧 Email ID: ${parsedResponse.email_id}`);
    }

    if (parsedResponse.recipients && Array.isArray(parsedResponse.recipients)) {
      console.log(`   📬 Recipients: ${parsedResponse.recipients.join(', ')}`);
    } else {
      console.log(`   📬 Recipients: notification recipients`);
    }

    console.log(`   ✨ ${data.service_name} notification delivered`);

  } catch (error) {
    console.error(`❌ Error sending ${process.env.SERVICE_NAME || 'Parts MCP'} notification!`);
    console.error(`   Error: ${error instanceof Error ? error.message : String(error)}`);

    if (error instanceof Error && 'cause' in error) {
      console.error(`   Cause: ${error.cause}`);
    }

    process.exit(1);
  }
}

// Run the script
sendNotification();
