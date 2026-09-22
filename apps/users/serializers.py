from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ('id', 'email', 'username', 'password')

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'username', 'created_at')
        read_only_fields = ('id', 'created_at')


class BootstrapSerializer(serializers.Serializer):
    installation_id = serializers.CharField(min_length=16, max_length=128, trim_whitespace=False)

    def validate_installation_id(self, value):
        if any('\x00' <= ch <= '\x1f' for ch in value):
            raise serializers.ValidationError('installation_id must not contain control characters.')
        return value
