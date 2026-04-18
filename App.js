import React, { useState, useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import {
  StyleSheet, Text, View, SafeAreaView, TouchableOpacity,
  Image, ActivityIndicator, Alert, ScrollView, TextInput
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { Colors } from './src/theme/colors';
import { scanRoom, saveItem, checkHealth } from './src/services/api';
import LoginScreen from './src/screens/LoginScreen';
import HistoryScreen from './src/screens/HistoryScreen';

export default function App() {
  // --- Auth State ---
  const [session, setSession] = useState(null);
  const [user, setUser] = useState(null);

  // --- Navigation State ---
  const [view, setView] = useState('scan'); // 'scan', 'history'

  // --- Scan State ---
  const [image, setImage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [savingIndex, setSavingIndex] = useState(null);
  const [homeName, setHomeName] = useState('My House');
  const [roomName, setRoomName] = useState('Living Room');

  // --- Connection check on mount ---
  useEffect(() => {
    checkHealth().then((res) => {
      if (res.status === 'unreachable') {
        Alert.alert(
          'Backend Unreachable',
          'Could not connect to the Holos server. Check that the Flask backend is running and the IP in src/config/env.js is correct.'
        );
      }
    });
  }, []);

  // --- Show Login if not authenticated ---
  if (!session) {
    return (
      <LoginScreen
        onLogin={(sessionData, userData) => {
          setSession(sessionData);
          setUser(userData);
        }}
      />
    );
  }

  // --- Show History ---
  if (view === 'history') {
    return (
      <HistoryScreen
        token={session.access_token}
        onBack={() => setView('scan')}
      />
    );
  }

  // --- Camera ---
  const pickImage = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission Denied', 'We need camera access to scan your room!');
      return;
    }

    let result = await ImagePicker.launchCameraAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: false,
      aspect: [4, 3],
      quality: 0.8,
    });

    if (!result.canceled) {
      const uri = result.assets[0].uri;
      setImage(uri);
      processScan(uri);
    }
  };

  const pickFromGallery = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission Denied', 'We need gallery access to scan photos!');
      return;
    }

    let result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: false,
      quality: 0.8,
    });

    if (!result.canceled) {
      const uri = result.assets[0].uri;
      setImage(uri);
      processScan(uri);
    }
  };

  const processScan = async (uri) => {
    setLoading(true);
    setResults([]);
    try {
      const response = await scanRoom(uri, homeName, roomName);
      if (response.success) {
        setResults(response.data);
      } else {
        Alert.alert('Scan Failed', response.error || 'Unknown error');
      }
    } catch (error) {
      Alert.alert('Connection Error', 'Could not reach Holos server. Check your IP in src/config/env.js');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveItem = async (item, index) => {
    setSavingIndex(index);
    try {
      const result = await saveItem(item, session.access_token);
      if (result.success) {
        Alert.alert('Saved!', `${item.name} has been added to your inventory.`);
        // Mark as saved in local state
        const updated = [...results];
        updated[index] = { ...updated[index], _saved: true, _dbId: result.data?.id };
        setResults(updated);
      } else {
        Alert.alert('Save Failed', result.error || 'Could not save item');
      }
    } catch (error) {
      Alert.alert('Error', 'Could not save item. Check your connection.');
    } finally {
      setSavingIndex(null);
    }
  };

  const handleLogout = () => {
    setSession(null);
    setUser(null);
    setResults([]);
    setImage(null);
    setView('scan');
  };

  const displayName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'User';

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" />

      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity style={styles.navBtn} onPress={() => setView('history')}>
          <Text style={styles.navBtnText}>📋 Inventory</Text>
        </TouchableOpacity>
        <View style={styles.headerCenter}>
          <Text style={styles.title}>Holos</Text>
          <Text style={styles.subtitle}>Welcome, {displayName}</Text>
        </View>
        <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
          <Text style={styles.logoutBtnText}>Logout</Text>
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.scrollContent}>
        {/* Preview Image */}
        {image && <Image source={{ uri: image }} style={styles.previewImage} />}

        {/* Loading State */}
        {loading && (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={Colors.primary} />
            <Text style={styles.loadingText}>Gemini AI is analyzing your room...</Text>
            <Text style={styles.loadingSubtext}>This may take 15-30 seconds</Text>
          </View>
        )}

        {/* Results */}
        {results.length > 0 && (
          <View style={styles.resultsList}>
            <Text style={styles.resultsTitle}>Items Found ({results.length})</Text>
            {results.map((item, index) => (
              <View key={index} style={styles.itemCard}>
                <View style={styles.thumbnailContainer}>
                  {item.thumbnail_url ? (
                    <Image source={{ uri: item.thumbnail_url }} style={styles.itemThumbnail} resizeMode="cover" />
                  ) : (
                    <View style={styles.noImagePlaceholder}>
                      <Text style={styles.noImageText}>✧</Text>
                    </View>
                  )}
                </View>
                <View style={styles.itemContent}>
                  <View style={styles.itemHeader}>
                    <Text style={styles.itemName} numberOfLines={1}>{item.name}</Text>
                    <Text style={styles.itemPrice}>${item.estimated_price_usd}</Text>
                  </View>
                  <Text style={styles.itemCategory}>{item.category}</Text>
                  {item.make && (
                    <Text style={styles.itemDetail}>{item.make} {item.model || ''}</Text>
                  )}
                  {item.condition && (
                    <View style={styles.conditionRow}>
                      <View style={[
                        styles.conditionBadge,
                        item.condition.toLowerCase().includes('excellent') && styles.badgeExcellent,
                        item.condition.toLowerCase().includes('good') && styles.badgeGood,
                        item.condition.toLowerCase().includes('fair') && styles.badgeFair,
                      ]}>
                        <Text style={styles.conditionText}>{item.condition}</Text>
                      </View>
                    </View>
                  )}
                  {/* Save Button */}
                  {!item._saved ? (
                    <TouchableOpacity
                      style={styles.saveBtn}
                      onPress={() => handleSaveItem(item, index)}
                      disabled={savingIndex === index}
                    >
                      {savingIndex === index ? (
                        <ActivityIndicator size="small" color="#000" />
                      ) : (
                        <Text style={styles.saveBtnText}>💾 Save to Inventory</Text>
                      )}
                    </TouchableOpacity>
                  ) : (
                    <View style={styles.savedBadge}>
                      <Text style={styles.savedBadgeText}>✓ Saved</Text>
                    </View>
                  )}
                </View>
              </View>
            ))}
          </View>
        )}

        {/* Action Buttons */}
        {!loading && (
          <View style={styles.actionArea}>
            <View style={styles.scanConfigRow}>
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>Property</Text>
                <TextInput 
                   style={styles.configInput} 
                   value={homeName} 
                   onChangeText={setHomeName} 
                   placeholder="e.g. Vacation Home" 
                   placeholderTextColor={Colors.textMuted} 
                />
              </View>
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>Room</Text>
                <TextInput 
                   style={styles.configInput} 
                   value={roomName} 
                   onChangeText={setRoomName} 
                   placeholder="e.g. Master Bedroom" 
                   placeholderTextColor={Colors.textMuted} 
                />
              </View>
            </View>

            <TouchableOpacity style={styles.scanButton} onPress={pickImage}>
              <Text style={styles.buttonText}>📸 Open Camera</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.galleryButton} onPress={pickFromGallery}>
              <Text style={styles.galleryButtonText}>🖼️ From Gallery</Text>
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bgDark,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: Colors.cardBorder,
  },
  headerCenter: {
    alignItems: 'center',
  },
  navBtn: {
    backgroundColor: Colors.cardBg,
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  navBtnText: {
    color: Colors.textMain,
    fontSize: 12,
    fontWeight: '600',
  },
  logoutBtn: {
    backgroundColor: 'rgba(239, 68, 68, 0.1)',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.3)',
  },
  logoutBtnText: {
    color: '#ef4444',
    fontSize: 12,
    fontWeight: '600',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: Colors.textMain,
    letterSpacing: -1,
  },
  subtitle: {
    fontSize: 12,
    color: Colors.primary,
    fontWeight: '500',
  },
  scrollContent: {
    padding: 20,
    flexGrow: 1,
  },
  previewImage: {
    width: '100%',
    height: 250,
    borderRadius: 16,
    marginBottom: 20,
  },
  loadingContainer: {
    padding: 40,
    alignItems: 'center',
  },
  loadingText: {
    color: Colors.primary,
    marginTop: 15,
    fontSize: 14,
    fontWeight: '500',
  },
  loadingSubtext: {
    color: Colors.textMuted,
    marginTop: 6,
    fontSize: 12,
  },
  resultsList: {
    marginTop: 10,
  },
  resultsTitle: {
    color: Colors.textMain,
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 15,
  },
  itemCard: {
    flexDirection: 'row',
    backgroundColor: Colors.cardBg,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 16,
    marginBottom: 12,
    overflow: 'hidden',
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 6,
    elevation: 3,
  },
  thumbnailContainer: {
    width: 120,
    backgroundColor: 'rgba(255, 255, 255, 0.03)',
  },
  itemThumbnail: {
    width: '100%',
    height: '100%',
  },
  noImagePlaceholder: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0f1115',
  },
  noImageText: {
    color: 'rgba(255,255,255,0.1)',
    fontSize: 32,
  },
  itemContent: {
    flex: 1,
    padding: 15,
    justifyContent: 'center',
  },
  itemHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  itemName: {
    color: Colors.textMain,
    fontSize: 16,
    fontWeight: '600',
    flex: 1,
  },
  itemPrice: {
    color: Colors.success,
    fontWeight: '700',
    fontSize: 16,
  },
  itemCategory: {
    color: Colors.textMuted,
    fontSize: 12,
    marginTop: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  itemDetail: {
    color: Colors.textMuted,
    fontSize: 13,
    marginTop: 4,
  },
  conditionRow: {
    flexDirection: 'row',
    marginTop: 8,
  },
  conditionBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 20,
    backgroundColor: 'rgba(0, 210, 255, 0.15)',
  },
  badgeExcellent: {
    backgroundColor: 'rgba(16, 185, 129, 0.2)',
  },
  badgeGood: {
    backgroundColor: 'rgba(0, 210, 255, 0.15)',
  },
  badgeFair: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
  },
  conditionText: {
    color: Colors.textMain,
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  saveBtn: {
    backgroundColor: Colors.primary,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: 'center',
    marginTop: 12,
  },
  saveBtnText: {
    color: '#000',
    fontWeight: '700',
    fontSize: 14,
  },
  savedBadge: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: 'center',
    marginTop: 12,
    borderWidth: 1,
    borderColor: 'rgba(16, 185, 129, 0.3)',
  },
  savedBadgeText: {
    color: Colors.success,
    fontWeight: '700',
    fontSize: 14,
  },
  actionArea: {
    marginTop: 'auto',
    paddingVertical: 20,
    gap: 12,
  },
  scanConfigRow: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 8,
  },
  inputGroup: {
    flex: 1,
  },
  inputLabel: {
    color: Colors.textMuted,
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 6,
    marginLeft: 4,
    fontWeight: '600',
  },
  configInput: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 12,
    padding: 12,
    color: Colors.textMain,
    fontSize: 14,
  },
  scanButton: {
    backgroundColor: Colors.primary,
    paddingVertical: 18,
    borderRadius: 30,
    alignItems: 'center',
    elevation: 5,
  },
  buttonText: {
    color: '#000',
    fontSize: 18,
    fontWeight: '700',
  },
  galleryButton: {
    backgroundColor: Colors.cardBg,
    paddingVertical: 16,
    borderRadius: 30,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  galleryButtonText: {
    color: Colors.textMain,
    fontSize: 16,
    fontWeight: '600',
  },
});
