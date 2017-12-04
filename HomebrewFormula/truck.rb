class Truck < Formula
  desc "Truck - the simplest dependency manager"
  url "https://github.com/Mazyod/homebrew-truck/archive/0.2.1.zip"
  version "0.2.0"
  # sha256 "85cc828a96735bdafcf29eb6291ca91bac846579bcef7308536e0c875d6c81d7"
  depends_on "awscli" => :recommended

  def install
    bin.install "truck.py" => "truck"
  end

  test do
  end
end
