import React, { useState } from 'react';
import {
    StyleSheet, Text, View, TextInput, TouchableOpacity,
    ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
    Image, Dimensions
} from 'react-native';
import { Colors } from '../theme/colors';
import { login, register } from '../services/api';

const { width } = Dimensions.get('window');

export default function LoginScreen({ onLogin }) {
    const [isLogin, setIsLogin] = useState(true);
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [fullName, setFullName] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async () => {
        if (!email.trim() || !password.trim()) {
            Alert.alert('Missing Fields', 'Please enter email and password.');
            return;
        }

        setLoading(true);
        try {
            let result;
            if (isLogin) {
                result = await login(email.trim(), password);
            } else {
                result = await register(email.trim(), password, fullName.trim());
                if (result.success) {
                    // Auto-login after registration
                    result = await login(email.trim(), password);
                }
            }

            if (result.success) {
                onLogin(result.session, result.user);
            } else {
                Alert.alert('Error', result.error || 'Something went wrong');
            }
        } catch (error) {
            Alert.alert(
                'Connection Error',
                'Could not reach Holos server.\n\nMake sure:\n1. The Flask backend is running\n2. Your phone is on the same Wi-Fi\n3. The IP in src/config/env.js is correct'
            );
        } finally {
            setLoading(false);
        }
    };

    const fillTestAccount = () => {
        setEmail('admin@holos.com');
        setPassword('holos2026');
    };

    return (
        <KeyboardAvoidingView
            style={styles.container}
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
            <View style={styles.inner}>
                {/* Logo & Brand */}
                <View style={styles.brandSection}>
                    <View style={styles.logoGlow}>
                        <Text style={styles.logoEmoji}>✦</Text>
                    </View>
                    <Text style={styles.appName}>Holos</Text>
                    <Text style={styles.tagline}>Intelligent Home Cataloging</Text>
                </View>

                {/* Form */}
                <View style={styles.formCard}>
                    <Text style={styles.formTitle}>
                        {isLogin ? 'Welcome Back' : 'Create Account'}
                    </Text>

                    {!isLogin && (
                        <View style={styles.inputGroup}>
                            <Text style={styles.label}>Full Name</Text>
                            <TextInput
                                style={styles.input}
                                placeholder="Your name"
                                placeholderTextColor={Colors.textMuted}
                                value={fullName}
                                onChangeText={setFullName}
                                autoCapitalize="words"
                            />
                        </View>
                    )}

                    <View style={styles.inputGroup}>
                        <Text style={styles.label}>Email</Text>
                        <TextInput
                            style={styles.input}
                            placeholder="you@example.com"
                            placeholderTextColor={Colors.textMuted}
                            value={email}
                            onChangeText={setEmail}
                            keyboardType="email-address"
                            autoCapitalize="none"
                            autoCorrect={false}
                        />
                    </View>

                    <View style={styles.inputGroup}>
                        <Text style={styles.label}>Password</Text>
                        <TextInput
                            style={styles.input}
                            placeholder="••••••••"
                            placeholderTextColor={Colors.textMuted}
                            value={password}
                            onChangeText={setPassword}
                            secureTextEntry
                        />
                    </View>

                    <TouchableOpacity
                        style={[styles.submitBtn, loading && styles.submitBtnDisabled]}
                        onPress={handleSubmit}
                        disabled={loading}
                    >
                        {loading ? (
                            <ActivityIndicator color="#000" />
                        ) : (
                            <Text style={styles.submitBtnText}>
                                {isLogin ? 'Sign In' : 'Create Account'}
                            </Text>
                        )}
                    </TouchableOpacity>

                    {/* Toggle mode */}
                    <TouchableOpacity
                        style={styles.toggleRow}
                        onPress={() => setIsLogin(!isLogin)}
                    >
                        <Text style={styles.toggleText}>
                            {isLogin ? "Don't have an account? " : 'Already have an account? '}
                        </Text>
                        <Text style={styles.toggleLink}>
                            {isLogin ? 'Sign Up' : 'Sign In'}
                        </Text>
                    </TouchableOpacity>
                </View>

                {/* Quick test account */}
                <TouchableOpacity style={styles.testAccountBtn} onPress={fillTestAccount}>
                    <Text style={styles.testAccountText}>
                        ⚡ Use Test Account (admin@holos.com)
                    </Text>
                </TouchableOpacity>
            </View>
        </KeyboardAvoidingView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: Colors.bgDark,
    },
    inner: {
        flex: 1,
        justifyContent: 'center',
        padding: 24,
    },
    brandSection: {
        alignItems: 'center',
        marginBottom: 40,
    },
    logoGlow: {
        width: 80,
        height: 80,
        borderRadius: 40,
        backgroundColor: 'rgba(0, 210, 255, 0.1)',
        borderWidth: 1,
        borderColor: 'rgba(0, 210, 255, 0.3)',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 16,
    },
    logoEmoji: {
        fontSize: 36,
        color: Colors.primary,
    },
    appName: {
        fontSize: 42,
        fontWeight: '800',
        color: Colors.textMain,
        letterSpacing: -2,
    },
    tagline: {
        fontSize: 14,
        color: Colors.primary,
        fontWeight: '500',
        marginTop: 4,
    },
    formCard: {
        backgroundColor: 'rgba(255, 255, 255, 0.04)',
        borderRadius: 24,
        padding: 24,
        borderWidth: 1,
        borderColor: 'rgba(255, 255, 255, 0.08)',
    },
    formTitle: {
        fontSize: 22,
        fontWeight: '700',
        color: Colors.textMain,
        marginBottom: 24,
        textAlign: 'center',
    },
    inputGroup: {
        marginBottom: 16,
    },
    label: {
        fontSize: 12,
        color: Colors.textMuted,
        textTransform: 'uppercase',
        letterSpacing: 1,
        marginBottom: 6,
        fontWeight: '600',
    },
    input: {
        backgroundColor: 'rgba(255, 255, 255, 0.06)',
        borderRadius: 12,
        padding: 14,
        color: Colors.textMain,
        fontSize: 16,
        borderWidth: 1,
        borderColor: 'rgba(255, 255, 255, 0.1)',
    },
    submitBtn: {
        backgroundColor: Colors.primary,
        borderRadius: 14,
        paddingVertical: 16,
        alignItems: 'center',
        marginTop: 8,
    },
    submitBtnDisabled: {
        opacity: 0.7,
    },
    submitBtnText: {
        color: '#000',
        fontSize: 16,
        fontWeight: '800',
        textTransform: 'uppercase',
        letterSpacing: 1.5,
    },
    toggleRow: {
        flexDirection: 'row',
        justifyContent: 'center',
        marginTop: 20,
    },
    toggleText: {
        color: Colors.textMuted,
        fontSize: 14,
    },
    toggleLink: {
        color: Colors.primary,
        fontSize: 14,
        fontWeight: '600',
    },
    testAccountBtn: {
        marginTop: 24,
        padding: 12,
        alignItems: 'center',
    },
    testAccountText: {
        color: Colors.textMuted,
        fontSize: 13,
        fontWeight: '500',
    },
});
