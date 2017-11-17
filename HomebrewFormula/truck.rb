class Truck < Formula
  desc "Truck - the simplest dependency manager"
  url "https://github.com/mazyod/homebrew-truck"
  version "0.0.1"
  # sha256 "85cc828a96735bdafcf29eb6291ca91bac846579bcef7308536e0c875d6c81d7"

  def install
    bin.install "../truck-client.py" => "truck"
  end

  test do
  end
end
