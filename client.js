// ==UserScript==
// @name         Discord Send Button
// @namespace    discord-send-btn
// @version      2.0
// @description  Send Discord messages to server
// @author       You
// @match        https://discord.com/*
// @match        https://*.discord.com/*
// @grant        GM_xmlhttpRequest
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    const BUTTON_CONFIG = {
        icon: '📋',
        tooltip: 'Send to server',
        action: 'send',
        color: '#5865f2'
    };

    let observer;
    let isInitialized = false;

    function createButton() {
        const button = document.createElement('button');
        button.innerHTML = BUTTON_CONFIG.icon;
        button.className = 'customButton_hover btn_send';
        button.setAttribute('aria-label', BUTTON_CONFIG.tooltip);
        button.title = BUTTON_CONFIG.tooltip;

        button.style.cssText = `
            background: transparent;
            border: none;
            border-radius: 3px;
            padding: 4px 6px;
            margin: 0 1px;
            cursor: pointer;
            color: var(--interactive-normal);
            font-size: 14px;
            transition: all 0.15s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            min-width: 30px;
            height: 30px;
        `;

        button.addEventListener('mouseenter', () => {
            button.style.backgroundColor = BUTTON_CONFIG.color + '25';
            button.style.color = BUTTON_CONFIG.color;
        });

        button.addEventListener('mouseleave', () => {
            button.style.backgroundColor = 'transparent';
            button.style.color = 'var(--interactive-normal)';
        });

        button.addEventListener('click', handleButtonClick);

        return button;
    }

    function handleButtonClick(event) {
        event.preventDefault();
        event.stopPropagation();

        const messageElement = event.target.closest('[id^="message-"]');
        if (!messageElement) return;

        const messageData = extractMessageData(messageElement);
        sendMessage(messageData);
    }

    function extractMessageData(messageElement) {
        const messageId = messageElement.id.replace('message-accessories-', '');
        const messageContent = messageElement.querySelector('[class*="messageContent"]');
        
        // Find timestamp in sibling contents container
        let timestamp = 0;
        let contentsContainer = messageElement.parentElement?.querySelector('[class*="contents"]');
        if (contentsContainer) {
            const timestampElement = contentsContainer.querySelector('[class*="timestamp"] time');
            if (timestampElement) {
                const datetimeAttr = timestampElement.getAttribute('datetime');
                if (datetimeAttr) {
                    timestamp = Math.floor(new Date(datetimeAttr).getTime() / 1000);
                }
            }
        }

        // Extract media content
        let mediaContent = '';
        const mediaSelectors = [
            '[class*="originalLink"]',
            '[class*="imageWrapper"] img',
            '[class*="videoWrapper"] video',
            '[class*="attachment"]',
            'a[href*="cdn.discordapp.com"]',
            'a[href*="media.discordapp.net"]'
        ];
        
        for (const selector of mediaSelectors) {
            const mediaElement = messageElement.querySelector(selector);
            if (mediaElement) {
                if (mediaElement.tagName === 'IMG' || mediaElement.tagName === 'VIDEO') {
                    mediaContent = mediaElement.src;
                } else if (mediaElement.href) {
                    mediaContent = mediaElement.href;
                }
                if (mediaContent) break;
            }
        }

        let body = `${messageContent?.querySelector('span')?.textContent || ''}`;
        if (messageContent?.querySelector('span')?.textContent?.length > 0) {
            body = body + " ";
        }
        
        body = body + mediaContent;
        
        return {
            id: messageId,
            content: body,
            timestamp: timestamp,
            element: messageElement
        };
    }

    function sendMessage(data) {
        const pathParts = window.location.pathname.split('/');
        const guildId = pathParts[2];
        const channelId = pathParts[3];
        
        const payload = {
            datepost: `<t:${data.timestamp}:f>`,
            datecopy: `<t:${Math.floor(Date.now() / 1000)}:f>`,
            content: data.content,
            source: `https://discord.com/channels/${guildId}/${channelId}/${data.id}`
        };

        GM_xmlhttpRequest({
            method: "POST",
            url: "http://127.0.0.1:8000/add",
            headers: {
                "Content-Type": "application/json"
            },
            data: JSON.stringify(payload),
            onload: function(response) {
                if (response.status >= 200 && response.status < 300) {
                    showNotification('Message sent successfully!', 'success');
                    console.log('Server response:', response.responseText);
                } else {
                    showNotification('Server error: ' + response.status, 'error');
                    console.error('Server error:', response.status, response.responseText);
                }
            },
            onerror: function(response) {
                showNotification('Connection failed!', 'error');
                console.error('Connection error:', response);
            },
            ontimeout: function() {
                showNotification('Request timeout!', 'error');
            },
            timeout: 10000
        });
    }

    function showNotification(text, type = 'info') {
        const colors = {
            success: '#57f287',
            error: '#ed4245',
            warning: '#fee75c',
            info: '#5865f2'
        };

        const notification = document.createElement('div');
        notification.textContent = text;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${colors[type]};
            color: ${type === 'warning' ? '#000' : '#fff'};
            padding: 12px 16px;
            border-radius: 6px;
            z-index: 10000;
            font-weight: 500;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            font-family: 'gg sans', 'Noto Sans', sans-serif;
            max-width: 300px;
            word-wrap: break-word;
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.transition = 'all 0.3s ease';
            notification.style.transform = 'translateX(100%)';
            notification.style.opacity = '0';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // Track right-click position and target
    let rightClickedLink = null;
    
    document.addEventListener('contextmenu', (e) => {
        // Find and save the link that was right-clicked
        rightClickedLink = null;
        let target = e.target;
        
        // Method 1: Check if target is a link (both <a> and [role="link"])
        if ((target.tagName === 'A' && target.href) || 
            (target.getAttribute && target.getAttribute('role') === 'link' && target.getAttribute('href'))) {
            rightClickedLink = target;
        } else {
            // Search for <a> link
            const parentLink = target.closest('a[href]');
            if (parentLink) {
                rightClickedLink = parentLink;
            } else {
                // Search for role="link" element
                const roleLink = target.closest('[role="link"][href]');
                if (roleLink) {
                    rightClickedLink = roleLink;
                }
            }
        }
        
        // Method 2: If no link found, search nearby elements
        if (!rightClickedLink) {
            // Search in siblings for both <a> and [role="link"]
            const parent = target.parentElement;
            if (parent) {
                const nearbyLink = parent.querySelector('a[href], [role="link"][href]');
                if (nearbyLink) {
                    rightClickedLink = nearbyLink;
                }
            }
            
            // Search in parent's parent
            if (!rightClickedLink && parent?.parentElement) {
                const nearbyLink = parent.parentElement.querySelector('a[href], [role="link"][href]');
                if (nearbyLink) {
                    rightClickedLink = nearbyLink;
                }
            }
        }
        
        const finalUrl = rightClickedLink?.href || rightClickedLink?.getAttribute('href');
        if (finalUrl) {
            console.log('Found link for context menu:', finalUrl);
        }
    }, true); // Use capture phase to catch it early

    // Clear rightClickedLink when clicking elsewhere
    document.addEventListener('click', (e) => {
        // Clear if clicking outside of context menu
        if (!e.target.closest('[role="menu"]') && !e.target.closest('[class*="menu"]')) {
            rightClickedLink = null;
        }
    });

    function addButtonToHoverGroup(hoverGroup) {
        if (!hoverGroup || hoverGroup.querySelector('.customButton_hover')) return;

        const button = createButton();

        const children = Array.from(hoverGroup.children);
        const insertBefore = children.find(child =>
            child.querySelector('[class*="more"]') ||
            child.getAttribute('aria-label')?.includes('More')
        );

        if (insertBefore) {
            hoverGroup.insertBefore(button, insertBefore);
        } else {
            hoverGroup.appendChild(button);
        }
    }

    function addCustomMenuOption(contextMenu) {
        // Check if already added
        if (contextMenu.querySelector('.custom-send-option')) return;

        // Find scroller and group with more flexible selectors
        const scroller = contextMenu.querySelector('[class*="scroller"]') || 
                        contextMenu.querySelector('div[style*="overflow"]') ||
                        contextMenu;
        
        const firstGroup = scroller.querySelector('[role="group"]') || 
                          scroller.querySelector('div:first-child') ||
                          scroller;

        if (!firstGroup) {
            console.log('Could not find group in context menu');
            return;
        }

        // Create custom menu item
        const customItem = document.createElement('div');
        customItem.className = 'item_c1e9c4 labelContainer_c1e9c4 colorDefault_c1e9c4 custom-send-option';
        customItem.setAttribute('role', 'menuitem');
        customItem.setAttribute('tabindex', '-1');
        customItem.setAttribute('data-menu-item', 'true');
        
        const label = document.createElement('div');
        label.className = 'label_c1e9c4';
        label.textContent = 'Send to server';
        
        customItem.appendChild(label);

        // Add hover styles
        customItem.addEventListener('mouseenter', () => {
            customItem.style.backgroundColor = 'var(--background-modifier-hover)';
        });

        customItem.addEventListener('mouseleave', () => {
            customItem.style.backgroundColor = '';
        });

        // Handle click
        customItem.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            handleContextMenuClick();
            
            // Close context menu
            contextMenu.closest('[class*="layer"]')?.remove();
        });

        // Add to first group
        firstGroup.appendChild(customItem);
        console.log('Added custom menu option');
    }

    function handleContextMenuClick() {
        if (rightClickedLink) {
            // Get URL from href attribute (works for both <a> and [role="link"])
            const url = rightClickedLink.href || rightClickedLink.getAttribute('href');
            
            if (url) {
                const linkData = {
                    url: url,
                    text: rightClickedLink.textContent || url,
                    timestamp: Math.floor(Date.now() / 1000)
                };

                sendLinkData(linkData);
                console.log('Sending link:', linkData.url);
                
                // Clear the link after using it
                rightClickedLink = null;
            } else {
                showNotification('No URL found!', 'error');
                console.log('Link element found but no href attribute');
            }
        } else {
            showNotification('No link found!', 'error');
            console.log('No link was saved from right-click');
        }
    }

    function sendLinkData(data) {
        const pathParts = window.location.pathname.split('/');
        const guildId = pathParts[2];
        const channelId = pathParts[3];
        
        const payload = {
            datepost: `<t:${data.timestamp}:f>`,
            datecopy: `<t:${Math.floor(Date.now() / 1000)}:f>`,
            content: data.url,
            source: `https://discord.com/channels/${guildId}/${channelId}`
        };

        GM_xmlhttpRequest({
            method: "POST",
            url: "http://127.0.0.1:8000/add",
            headers: {
                "Content-Type": "application/json"
            },
            data: JSON.stringify(payload),
            onload: function(response) {
                if (response.status >= 200 && response.status < 300) {
                    showNotification('Link sent successfully!', 'success');
                    console.log('Server response:', response.responseText);
                } else {
                    showNotification('Server error: ' + response.status, 'error');
                    console.error('Server error:', response.status, response.responseText);
                }
            },
            onerror: function(response) {
                showNotification('Connection failed!', 'error');
                console.error('Connection error:', response);
            },
            ontimeout: function() {
                showNotification('Request timeout!', 'error');
            },
            timeout: 10000
        });
    }

    function checkForHoverGroups() {
        const selectors = [
            '[class*="hoverButtonGroup"]',
            '[class*="imageAccessor"]',
            '[class*="imageAccessory"]'  // Добавил этот селектор
        ];

        selectors.forEach(selector => {
            const hoverGroups = document.querySelectorAll(selector);
            hoverGroups.forEach(group => {
                if (group.offsetParent !== null && !group.querySelector('.customButton_hover')) {
                    addButtonToHoverGroup(group);
                }
            });
        });
    }

    function initObserver() {
        if (observer) observer.disconnect();

        observer = new MutationObserver((mutations) => {
            let shouldCheck = false;

            mutations.forEach(mutation => {
                if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach(node => {
                        if (node.nodeType === Node.ELEMENT_NODE && node.className) {
                            // Check for hover buttons
                            if (node.className.includes('hover') ||
                                node.className.includes('button') ||
                                node.className.includes('toolbar')) {
                                shouldCheck = true;
                            }
                            
                            // Check for context menu elements
                            if (node.className.includes('menu') ||
                                node.className.includes('layer') ||
                                node.className.includes('clickTrap') ||
                                node.id === 'attachment-link-context') {
                                console.log('Detected menu-related element:', node.className || node.id);
                                
                                // Look for context menu in this node or its children
                                setTimeout(() => {
                                    const contextMenu = document.querySelector('#attachment-link-context') ||
                                                      document.querySelector('[role="menu"]');
                                    if (contextMenu && rightClickedLink) {
                                        console.log('Found context menu after menu element appeared');
                                        addCustomMenuOption(contextMenu);
                                    }
                                }, 10);
                            }
                        }
                    });
                }
            });

            if (shouldCheck) {
                setTimeout(checkForHoverGroups, 50);
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: false
        });
    }

    function initContextMenuObserver() {
        const contextObserver = new MutationObserver((mutations) => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // Debug: log all new nodes to see what appears
                        if (node.id || node.className) {
                            console.log('New node:', node.tagName, node.id || '', node.className || '');
                        }
                        
                        // Look for context menu
                        const contextMenu = node.querySelector('#attachment-link-context') || 
                                          (node.id === 'attachment-link-context' ? node : null) ||
                                          (node.getAttribute && node.getAttribute('role') === 'menu' ? node : null);
                        
                        if (contextMenu && rightClickedLink) {
                            console.log('Found context menu when rightClickedLink exists:', contextMenu);
                            addCustomMenuOption(contextMenu);
                        } else if (contextMenu) {
                            console.log('Found context menu but no rightClickedLink');
                        }
                    }
                });
            });
        });

        contextObserver.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    function waitForDiscord() {
        if (document.querySelector('[class*="app-"]') && !isInitialized) {
            console.log('Discord loaded, initializing send button...');
            isInitialized = true;
            initObserver();
            checkForHoverGroups();
            
            setInterval(checkForHoverGroups, 2000);
        } else if (!isInitialized) {
            setTimeout(waitForDiscord, 1000);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', waitForDiscord);
    } else {
        waitForDiscord();
    }

    console.log('Discord Send Button loaded');
})();