import React, { useState, useEffect, useCallback } from 'react';
import {
    StyleSheet, Text, View, FlatList,
    Image, TouchableOpacity, ActivityIndicator,
    TextInput, RefreshControl, Alert, Modal, ScrollView
} from 'react-native';
import { Colors } from '../theme/colors';
import { fetchItems, archiveItem as apiArchiveItem, getResaleListing } from '../services/api';

export default function HistoryScreen({ token, onBack }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [showArchived, setShowArchived] = useState(false);
    const [selectedItem, setSelectedItem] = useState(null);
    const [viewMode, setViewMode] = useState('isolated'); // isolated | room

    useEffect(() => {
        loadItems();
    }, [showArchived]);

    const loadItems = async (query = searchQuery) => {
        setLoading(true);
        try {
            const result = await fetchItems(token, { query, archived: showArchived });
            if (result.success) {
                setItems(result.data || []);
            } else {
                console.error('Fetch Error:', result.error);
            }
        } catch (error) {
            console.error('Network Error:', error);
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    };

    const onRefresh = useCallback(() => {
        setRefreshing(true);
        loadItems();
    }, [searchQuery, showArchived]);

    const handleSearch = (text) => {
        setSearchQuery(text);
        // Debounce: only search after user stops typing
        clearTimeout(handleSearch._timer);
        handleSearch._timer = setTimeout(() => loadItems(text), 400);
    };

    const handleArchive = async (itemId) => {
        try {
            await apiArchiveItem(itemId, token);
            // Remove from current view
            setItems(prev => prev.filter(i => i.id !== itemId));
        } catch (error) {
            Alert.alert('Error', 'Could not archive item');
        }
    };

    const handleSell = async (itemId, itemName) => {
        try {
            const result = await getResaleListing(itemId, token);
            if (result.success) {
                const listing = result.listing;
                Alert.alert(
                    '💰 AI Listing Ready',
                    `Title: ${listing.listing_title}\n\n${listing.listing_description?.substring(0, 200)}...`,
                    [
                        { text: 'Close', style: 'cancel' },
                    ]
                );
            } else {
                Alert.alert('Error', result.error || 'Could not generate listing');
            }
        } catch (error) {
            Alert.alert('Error', 'Could not reach AI service');
        }
    };

    const totalValue = items.reduce((sum, item) => sum + (parseFloat(item.estimated_price_usd) || 0), 0);

    const renderItem = ({ item }) => (
        <TouchableOpacity 
            style={styles.card}
            activeOpacity={0.8}
            onPress={() => { setSelectedItem(item); setViewMode('isolated'); }}
        >
            <View style={styles.thumbnailContainer}>
                {item.thumbnail_url ? (
                    <Image
                        source={{ uri: item.thumbnail_url }}
                        style={styles.thumbnail}
                        resizeMode="cover"
                    />
                ) : (
                    <View style={styles.noImagePlaceholder}>
                        <Text style={styles.noImageText}>✧</Text>
                    </View>
                )}
            </View>
            <View style={styles.cardContent}>
                <Text style={styles.itemName} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.itemCategory}>{item.category}</Text>
                <Text style={styles.itemPrice}>${parseFloat(item.estimated_price_usd || 0).toLocaleString()}</Text>
                {item.home_name && (
                    <Text style={styles.itemLocation}>📍 {item.home_name} — {item.room_name}</Text>
                )}
            </View>
            <View style={styles.actionCol}>
                <TouchableOpacity
                    style={styles.sellBtn}
                    onPress={() => handleSell(item.id, item.name)}
                >
                    <Text style={styles.sellBtnText}>💰</Text>
                </TouchableOpacity>
                <TouchableOpacity
                    style={styles.archiveBtn}
                    onPress={() => handleArchive(item.id)}
                >
                    <Text style={styles.archiveBtnText}>📦</Text>
                </TouchableOpacity>
                </TouchableOpacity>
            </View>
        </TouchableOpacity>
    );

    return (
        <View style={styles.container}>
            {/* Header */}
            <View style={styles.header}>
                <TouchableOpacity onPress={onBack}>
                    <Text style={styles.backButton}>← Back</Text>
                </TouchableOpacity>
                <Text style={styles.title}>Your Inventory</Text>
                <View style={{ width: 50 }} />
            </View>

            {/* Summary Bar */}
            <View style={styles.summaryBar}>
                <View style={styles.summaryItem}>
                    <Text style={styles.summaryValue}>{items.length}</Text>
                    <Text style={styles.summaryLabel}>Items</Text>
                </View>
                <View style={styles.summaryDivider} />
                <View style={styles.summaryItem}>
                    <Text style={styles.summaryValueHighlight}>${totalValue.toLocaleString()}</Text>
                    <Text style={styles.summaryLabel}>Total Value</Text>
                </View>
            </View>

            {/* Search */}
            <View style={styles.searchContainer}>
                <TextInput
                    style={styles.searchInput}
                    placeholder="Search items..."
                    placeholderTextColor={Colors.textMuted}
                    value={searchQuery}
                    onChangeText={handleSearch}
                />
            </View>

            {/* Tabs */}
            <View style={styles.tabRow}>
                <TouchableOpacity
                    style={[styles.tab, !showArchived && styles.tabActive]}
                    onPress={() => setShowArchived(false)}
                >
                    <Text style={[styles.tabText, !showArchived && styles.tabTextActive]}>Active</Text>
                </TouchableOpacity>
                <TouchableOpacity
                    style={[styles.tab, showArchived && styles.tabActive]}
                    onPress={() => setShowArchived(true)}
                >
                    <Text style={[styles.tabText, showArchived && styles.tabTextActive]}>Archived</Text>
                </TouchableOpacity>
            </View>

            {/* Items List */}
            {loading && !refreshing ? (
                <View style={styles.center}>
                    <ActivityIndicator size="large" color={Colors.primary} />
                </View>
            ) : (
                <FlatList
                    data={items}
                    keyExtractor={(item) => item.id?.toString() || Math.random().toString()}
                    renderItem={renderItem}
                    contentContainerStyle={styles.list}
                    refreshControl={
                        <RefreshControl
                            refreshing={refreshing}
                            onRefresh={onRefresh}
                            tintColor={Colors.primary}
                        />
                    }
                    ListEmptyComponent={
                        <View style={styles.emptyContainer}>
                            <Text style={styles.emptyEmoji}>📦</Text>
                            <Text style={styles.emptyText}>
                                {showArchived ? 'No archived items.' : 'No items scanned yet.'}
                            </Text>
                            <Text style={styles.emptySubtext}>
                                {showArchived ? 'Items you archive will appear here.' : 'Take a photo to start cataloging!'}
                            </Text>
                        </View>
                    }
                />
            )}

            {/* Item Detail Hybrid Modal */}
            <Modal visible={!!selectedItem} animationType="slide" transparent={true}>
                {selectedItem && (
                    <View style={styles.modalOverlay}>
                        <View style={styles.modalCard}>
                            <TouchableOpacity style={styles.closeBtn} onPress={() => setSelectedItem(null)}>
                                <Text style={styles.closeBtnText}>✕</Text>
                            </TouchableOpacity>
                            <ScrollView style={styles.modalScroll} bounces={false}>
                                <View style={styles.hybridImageContainer}>
                                    {viewMode === 'isolated' ? (
                                        selectedItem.thumbnail_url ? (
                                            <Image source={{ uri: selectedItem.thumbnail_url }} style={styles.modalImageSquare} resizeMode="contain" />
                                        ) : (
                                            <View style={[styles.modalImageSquare, styles.noImagePlaceholder]}>
                                                <Text style={styles.noImageText}>✧</Text>
                                            </View>
                                        )
                                    ) : (
                                        <View style={styles.contextContainer}>
                                            <Image source={{ uri: selectedItem.original_image_url }} style={styles.modalImageRoom} resizeMode="cover" />
                                            <View style={styles.contextOverlay}>
                                                <Text style={styles.contextOverlayText}>Original Room Matrix</Text>
                                            </View>
                                        </View>
                                    )}
                                </View>

                                {/* Hybrid Toggle Row */}
                                {selectedItem.original_image_url && (
                                    <View style={styles.hybridToggleRow}>
                                        <TouchableOpacity 
                                            style={[styles.hybridTab, viewMode === 'isolated' && styles.hybridTabActive]}
                                            onPress={() => setViewMode('isolated')}
                                        >
                                            <Text style={[styles.hybridTabText, viewMode === 'isolated' && styles.hybridTabTextActive]}>Isolated View</Text>
                                        </TouchableOpacity>
                                        <TouchableOpacity 
                                            style={[styles.hybridTab, viewMode === 'room' && styles.hybridTabActive]}
                                            onPress={() => setViewMode('room')}
                                        >
                                            <Text style={[styles.hybridTabText, viewMode === 'room' && styles.hybridTabTextActive]}>View Context</Text>
                                        </TouchableOpacity>
                                    </View>
                                )}

                                <View style={styles.modalContentBox}>
                                    <Text style={styles.modalTitle}>{selectedItem.name}</Text>
                                    <View style={styles.modalBadges}>
                                        <Text style={styles.modalBadgeText}>{selectedItem.category}</Text>
                                        <Text style={styles.modalBadgeText}>•</Text>
                                        <Text style={styles.modalBadgeText}>{selectedItem.condition}</Text>
                                    </View>
                                    <Text style={styles.modalPrice}>${parseFloat(selectedItem.estimated_price_usd || 0).toLocaleString()}</Text>
                                    
                                    <View style={styles.modalDataBlock}>
                                        <Text style={styles.modalSectionLabel}>Make / Model</Text>
                                        <Text style={styles.modalBodyText}>
                                            {selectedItem.make || 'Unknown'} {selectedItem.model && selectedItem.model !== 'Unidentified' ? `- ${selectedItem.model}` : ''}
                                        </Text>
                                    </View>
                                    
                                    <View style={styles.modalDataBlock}>
                                        <Text style={styles.modalSectionLabel}>Dimensions</Text>
                                        <Text style={styles.modalBodyText}>{selectedItem.estimated_dimensions || 'Not specified'}</Text>
                                    </View>
                                    
                                    {selectedItem.condition_notes && (
                                        <View style={styles.modalDataBlock}>
                                            <Text style={styles.modalSectionLabel}>Condition Notes</Text>
                                            <Text style={styles.modalBodyText}>{selectedItem.condition_notes}</Text>
                                        </View>
                                    )}
                                </View>
                            </ScrollView>
                        </View>
                    </View>
                )}
            </Modal>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: Colors.bgDark,
    },
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: 20,
        paddingTop: 50,
        borderBottomWidth: 1,
        borderBottomColor: Colors.cardBorder,
    },
    title: {
        color: Colors.textMain,
        fontSize: 20,
        fontWeight: '700',
    },
    backButton: {
        color: Colors.primary,
        fontSize: 16,
        fontWeight: '600',
    },
    summaryBar: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: 16,
        paddingHorizontal: 20,
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        borderBottomWidth: 1,
        borderBottomColor: Colors.cardBorder,
    },
    summaryItem: {
        alignItems: 'center',
        paddingHorizontal: 24,
    },
    summaryDivider: {
        width: 1,
        height: 30,
        backgroundColor: Colors.cardBorder,
    },
    summaryValue: {
        color: Colors.textMain,
        fontSize: 24,
        fontWeight: '800',
    },
    summaryValueHighlight: {
        color: Colors.success,
        fontSize: 24,
        fontWeight: '800',
    },
    summaryLabel: {
        color: Colors.textMuted,
        fontSize: 11,
        textTransform: 'uppercase',
        letterSpacing: 1,
        marginTop: 2,
    },
    searchContainer: {
        paddingHorizontal: 20,
        paddingVertical: 12,
    },
    searchInput: {
        backgroundColor: 'rgba(255, 255, 255, 0.06)',
        borderRadius: 12,
        padding: 12,
        color: Colors.textMain,
        fontSize: 14,
        borderWidth: 1,
        borderColor: Colors.cardBorder,
    },
    tabRow: {
        flexDirection: 'row',
        paddingHorizontal: 20,
        gap: 8,
        marginBottom: 8,
    },
    tab: {
        paddingVertical: 8,
        paddingHorizontal: 20,
        borderRadius: 20,
        backgroundColor: 'rgba(255, 255, 255, 0.04)',
        borderWidth: 1,
        borderColor: Colors.cardBorder,
    },
    tabActive: {
        backgroundColor: Colors.primary,
        borderColor: Colors.primary,
    },
    tabText: {
        color: Colors.textMuted,
        fontSize: 13,
        fontWeight: '600',
    },
    tabTextActive: {
        color: '#000',
    },
    list: {
        padding: 20,
    },
    card: {
        flexDirection: 'row',
        backgroundColor: Colors.cardBg,
        borderRadius: 16,
        marginBottom: 12,
        borderWidth: 1,
        borderColor: Colors.cardBorder,
        overflow: 'hidden',
        // Subtle drop shadow for glassmorphism pop
        shadowColor: "#000",
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.1,
        shadowRadius: 6,
        elevation: 3,
    },
    thumbnailContainer: {
        width: 100,
        height: '100%',
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        borderTopLeftRadius: 16,
        borderBottomLeftRadius: 16,
        overflow: 'hidden',
    },
    thumbnail: {
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
    cardContent: {
        flex: 1,
        padding: 12,
        justifyContent: 'center',
    },
    itemName: {
        color: Colors.textMain,
        fontSize: 15,
        fontWeight: '600',
    },
    itemCategory: {
        color: Colors.textMuted,
        fontSize: 11,
        marginTop: 2,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
    },
    itemPrice: {
        color: Colors.success,
        fontWeight: '700',
        marginTop: 4,
        fontSize: 15,
    },
    itemLocation: {
        color: Colors.textMuted,
        fontSize: 11,
        marginTop: 3,
    },
    actionCol: {
        justifyContent: 'center',
        gap: 6,
        paddingHorizontal: 10,
    },
    sellBtn: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: 'rgba(16, 185, 129, 0.15)',
        justifyContent: 'center',
        alignItems: 'center',
    },
    sellBtnText: {
        fontSize: 16,
    },
    archiveBtn: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: 'rgba(255, 255, 255, 0.06)',
        justifyContent: 'center',
        alignItems: 'center',
    },
    archiveBtnText: {
        fontSize: 16,
    },
    center: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
    },
    emptyContainer: {
        alignItems: 'center',
        marginTop: 60,
    },
    emptyEmoji: {
        fontSize: 48,
        marginBottom: 16,
    },
    emptyText: {
        color: Colors.textMuted,
        textAlign: 'center',
        fontSize: 16,
        fontWeight: '600',
    },
    emptySubtext: {
        color: Colors.textMuted,
        textAlign: 'center',
        fontSize: 13,
        marginTop: 6,
        opacity: 0.6,
    },
    /* Modal Styles */
    modalOverlay: {
        flex: 1,
        backgroundColor: 'rgba(0,0,0,0.85)',
        justifyContent: 'flex-end',
    },
    modalCard: {
        backgroundColor: Colors.cardBg,
        borderTopLeftRadius: 28,
        borderTopRightRadius: 28,
        height: '88%',
        overflow: 'hidden',
        borderWidth: 1,
        borderColor: Colors.cardBorder,
        shadowColor: "#000",
        shadowOffset: { width: 0, height: -10 },
        shadowOpacity: 0.5,
        shadowRadius: 20,
        elevation: 10,
    },
    closeBtn: {
        position: 'absolute',
        top: 20,
        right: 20,
        zIndex: 10,
        width: 32,
        height: 32,
        borderRadius: 16,
        backgroundColor: 'rgba(0,0,0,0.6)',
        alignItems: 'center',
        justifyContent: 'center',
    },
    closeBtnText: {
        color: '#fff',
        fontSize: 16,
        fontWeight: 'bold',
    },
    modalScroll: {
        flex: 1,
    },
    hybridImageContainer: {
        width: '100%',
        height: 360,
        backgroundColor: '#0a0a0d',
    },
    modalImageSquare: {
        width: '100%',
        height: '100%',
    },
    modalImageRoom: {
        width: '100%',
        height: '100%',
    },
    contextContainer: {
        flex: 1,
        position: 'relative',
    },
    contextOverlay: {
        position: 'absolute',
        bottom: 16,
        left: 16,
        backgroundColor: 'rgba(0,0,0,0.7)',
        paddingHorizontal: 12,
        paddingVertical: 6,
        borderRadius: 8,
        borderWidth: 1,
        borderColor: 'rgba(255,255,255,0.1)',
    },
    contextOverlayText: {
        color: '#fff',
        fontSize: 12,
        fontWeight: '600',
        textTransform: 'uppercase',
        letterSpacing: 1,
    },
    hybridToggleRow: {
        flexDirection: 'row',
        paddingHorizontal: 24,
        paddingTop: 24,
        paddingBottom: 8,
        gap: 12,
    },
    hybridTab: {
        flex: 1,
        paddingVertical: 12,
        alignItems: 'center',
        borderRadius: 12,
        backgroundColor: 'rgba(255,255,255,0.04)',
        borderWidth: 1,
        borderColor: 'rgba(255,255,255,0.02)',
    },
    hybridTabActive: {
        backgroundColor: Colors.primary,
        borderColor: Colors.primary,
    },
    hybridTabText: {
        color: Colors.textMuted,
        fontWeight: '700',
        fontSize: 13,
    },
    hybridTabTextActive: {
        color: '#000',
    },
    modalContentBox: {
        padding: 24,
        paddingBottom: 60,
    },
    modalTitle: {
        fontSize: 28,
        fontWeight: '800',
        color: Colors.textMain,
    },
    modalBadges: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        marginTop: 8,
    },
    modalBadgeText: {
        color: Colors.textMuted,
        fontSize: 13,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
    },
    modalPrice: {
        color: Colors.success,
        fontSize: 26,
        fontWeight: '800',
        marginTop: 16,
        marginBottom: 24,
    },
    modalDataBlock: {
        marginBottom: 16,
        backgroundColor: 'rgba(255,255,255,0.03)',
        padding: 16,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: 'rgba(255,255,255,0.05)',
    },
    modalSectionLabel: {
        color: Colors.textMuted,
        fontSize: 12,
        textTransform: 'uppercase',
        letterSpacing: 1,
        marginBottom: 6,
    },
    modalBodyText: {
        color: Colors.textMain,
        fontSize: 15,
        lineHeight: 22,
    },
});
