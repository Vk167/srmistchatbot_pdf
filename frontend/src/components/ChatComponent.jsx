// ChatComponent.jsx - Example React Component for the Chatbot

import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

// const API_BASE_URL = 'http://localhost:8000';
const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const ChatComponent = () => {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [queryCount, setQueryCount] = useState(0);
  const [requiresEmail, setRequiresEmail] = useState(false);
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef(null);

  // Auto-scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Initialize session on mount
  useEffect(() => {
    const initSession = async () => {
      try {
        const response = await axios.get(`${API_BASE_URL}/health`);
        console.log('Backend health:', response.data);
      } catch (error) {
        console.error('Backend connection failed:', error);
      }
    };
    initSession();
  }, []);

  // Send message (non-streaming)
  const sendMessage = async () => {
    if (!inputMessage.trim()) return;

    const userMessage = { role: 'user', content: inputMessage };
    setMessages((prev) => [...prev, userMessage]);
    setInputMessage('');
    setIsLoading(true);

    try {
      const response = await axios.post(`${API_BASE_URL}/chat`, {
        message: inputMessage,
        session_id: sessionId,
        email: email || null,
      });

      const { answer, sources, session_id, query_count, requires_email } = response.data;

      // Update session
      setSessionId(session_id);
      setQueryCount(query_count);
      setRequiresEmail(requires_email);

      // Add bot response
      const botMessage = {
        role: 'assistant',
        content: answer,
        sources: sources,
      };
      setMessages((prev) => [...prev, botMessage]);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage = {
        role: 'assistant',
        content: 'Sorry, something went wrong. Please try again.',
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Send message (streaming)
  const sendMessageStreaming = async () => {
    if (!inputMessage.trim()) return;

    const userMessage = { role: 'user', content: inputMessage };
    setMessages((prev) => [...prev, userMessage]);
    setInputMessage('');
    setIsStreaming(true);

    // Add placeholder for bot response
    const botMessageIndex = messages.length + 1;
    setMessages((prev) => [...prev, { role: 'assistant', content: '', sources: null }]);

    try {
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: inputMessage,
          session_id: sessionId,
          email: email || null,
        }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));

            if (data.type === 'chunk') {
              // Update message content
              setMessages((prev) => {
                const updated = [...prev];
                updated[botMessageIndex] = {
                  role: 'assistant',
                  content: data.content,
                  sources: null,
                };
                return updated;
              });
              setSessionId(data.session_id);
            } else if (data.type === 'sources') {
              // Add sources
              setMessages((prev) => {
                const updated = [...prev];
                updated[botMessageIndex].sources = data.content;
                return updated;
              });
            } else if (data.type === 'done') {
              setQueryCount(data.query_count);
            } else if (data.type === 'requires_email') {
              setRequiresEmail(true);
              setSessionId(data.session_id);
            } else if (data.type === 'error') {
              setMessages((prev) => {
                const updated = [...prev];
                updated[botMessageIndex].content = data.content;
                return updated;
              });
            }
          }
        }
      }
    } catch (error) {
      console.error('Streaming error:', error);
      setMessages((prev) => {
        const updated = [...prev];
        updated[botMessageIndex] = {
          role: 'assistant',
          content: 'Sorry, something went wrong. Please try again.',
        };
        return updated;
      });
    } finally {
      setIsStreaming(false);
    }
  };

  // Submit email
  const submitEmail = async () => {
    if (!email.trim()) {
      alert('Please enter a valid email');
      return;
    }

    try {
      const response = await axios.post(`${API_BASE_URL}/email/submit`, {
        email: email,
        session_id: sessionId,
      });

      if (response.data.success) {
        setRequiresEmail(false);
        alert('Email saved! You can continue chatting.');
      } else {
        alert(`Failed to save email: ${response.data.message}`);
      }
    } catch (error) {
      console.error('Email submission error:', error);
      alert('Failed to save email. Please try again.');
    }
  };

  // Handle Enter key
  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessageStreaming(); // Use streaming version
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2> SRMIST University Assistant</h2>
        <p>Ask me anything about the university!</p>
      </div>

      {/* Email Prompt Modal */}
      {requiresEmail && (
        <div style={styles.emailModal}>
          <div style={styles.emailCard}>
            <h3> Query Limit Reached</h3>
            <p>You've used your {queryCount} free queries. Please enter your email to continue.</p>
            <input
              type="email"
              placeholder="your.email@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={styles.emailInput}
            />
            <button onClick={submitEmail} style={styles.submitButton}>
              Submit Email
            </button>
            <button onClick={() => setRequiresEmail(false)} style={styles.cancelButton}>
              Maybe Later
            </button>
          </div>
        </div>
      )}

      {/* Chat Messages */}
      <div style={styles.messagesContainer}>
        {messages.map((msg, index) => (
          <div
            key={index}
            style={{
              ...styles.message,
              ...(msg.role === 'user' ? styles.userMessage : styles.botMessage),
            }}
          >
            <div style={styles.messageContent}>
              {msg.content}
              {msg.sources && (
                <div style={styles.sources} dangerouslySetInnerHTML={{ __html: msg.sources }} />
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div style={styles.message}>
            <div style={styles.loader}>Thinking...</div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div style={styles.inputContainer}>
        <textarea
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Type your question here..."
          style={styles.input}
          rows={2}
          disabled={isStreaming || isLoading}
        />
        <button
          onClick={sendMessageStreaming}
          style={styles.sendButton}
          disabled={isStreaming || isLoading || !inputMessage.trim()}
        >
          {isStreaming || isLoading ? '⏳' : '➤'}
        </button>
      </div>

      <div style={styles.footer}>
        <small> SRMIST Chatbot is experimental & accuracy might vary</small>
        <br />
        <small>Developed by SRMTech | Built for SRMIST University</small>
      </div>
    </div>
  );
};

// Inline styles (move to CSS file in production)
const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    maxWidth: '1000px',
    margin: '0 auto',
    fontFamily: "'Segoe UI', sans-serif",
    backgroundColor: '#f5f5f5',
  },
  header: {
    padding: '20px',
    backgroundColor: '#007bff',
    color: 'white',
    textAlign: 'center',
  },
  messagesContainer: {
    flex: 1,
    overflowY: 'auto',
    padding: '20px',
    backgroundColor: '#fff',
  },
  message: {
    marginBottom: '15px',
    display: 'flex',
  },
  userMessage: {
    justifyContent: 'flex-end',
  },
  botMessage: {
    justifyContent: 'flex-start',
  },
  messageContent: {
    maxWidth: '70%',
    padding: '12px 16px',
    borderRadius: '12px',
    backgroundColor: '#e3f2fd',
    wordWrap: 'break-word',
  },
  sources: {
    marginTop: '10px',
    fontSize: '12px',
    color: '#555',
    borderTop: '1px solid #ccc',
    paddingTop: '8px',
  },
  inputContainer: {
    display: 'flex',
    padding: '15px',
    backgroundColor: '#fff',
    borderTop: '1px solid #ddd',
  },
  input: {
    flex: 1,
    padding: '10px',
    border: '1px solid #ccc',
    borderRadius: '5px',
    fontSize: '14px',
    resize: 'none',
  },
  sendButton: {
    marginLeft: '10px',
    padding: '10px 20px',
    backgroundColor: '#007bff',
    color: 'white',
    border: 'none',
    borderRadius: '5px',
    cursor: 'pointer',
    fontSize: '18px',
  },
  footer: {
    padding: '10px',
    textAlign: 'center',
    color: '#666',
    fontSize: '12px',
    backgroundColor: '#fff',
  },
  emailModal: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  emailCard: {
    backgroundColor: 'white',
    padding: '30px',
    borderRadius: '10px',
    maxWidth: '400px',
    textAlign: 'center',
  },
  emailInput: {
    width: '100%',
    padding: '10px',
    margin: '15px 0',
    border: '1px solid #ccc',
    borderRadius: '5px',
    fontSize: '14px',
  },
  submitButton: {
    width: '100%',
    padding: '10px',
    marginBottom: '10px',
    backgroundColor: '#007bff',
    color: 'white',
    border: 'none',
    borderRadius: '5px',
    cursor: 'pointer',
    fontWeight: 'bold',
  },
  cancelButton: {
    width: '100%',
    padding: '10px',
    backgroundColor: '#6c757d',
    color: 'white',
    border: 'none',
    borderRadius: '5px',
    cursor: 'pointer',
  },
  loader: {
    padding: '12px 16px',
    backgroundColor: '#f0f0f0',
    borderRadius: '12px',
    color: '#666',
  },
};

export default ChatComponent;